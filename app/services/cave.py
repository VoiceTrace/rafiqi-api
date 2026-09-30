import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ErrorCode
from app.models.conversation import Conversation
from app.models.message import ConversationMessage, MessageRole
from app.models.profile import ProfileCard, StudentProfile
from app.schemas.profile import CARD_DEFINITIONS, CardKey
from app.models.user import User
from app.services import profile_extraction
from app.services.llm import LLMError, chat_completion
from app.services.safety import SAFETY_SCRIPTS, classify_message

_HISTORY_LIMIT = 12

# A conversation with no message in the last 12h stops being the "active"
# one a plain visit resumes — the next visit starts fresh instead. Any
# conversation, active or not, stays resumable by its own id at any time.
_ACTIVE_WINDOW = timedelta(hours=12)

# A3 runs automatically roughly every this many stored messages within a
# conversation (not exchanges — see _maybe_extract), rather than at an
# explicit "end" (there is no end concept anymore).
_EXTRACTION_TURN_INTERVAL = 20

_PERSONA_SYSTEM_PROMPT = """You are Rafiqi, a warm, curious, playful AI companion for school \
students, currently talking with {student_name} in "Rafiqi's Cave" — a relaxed space that \
isn't tied to any lesson or graded work.

Your real goal is to build up a picture of who {student_name} is as a learner: how they learn \
best, what drives them, how they're feeling about school day to day, their study habits, the \
language(s) and company they learn best in, and the world/context they're learning in at home. \
But never make it feel like an interview, a form, or an assessment — that breaks trust \
immediately with a kid. Get there sideways: tell a bit of a story, float a scenario, riff on \
whatever they just said, follow a tangent if it's fun, and let one good question emerge \
naturally rather than firing off a checklist. Stay genuinely interesting — surprise them \
sometimes, be a little silly, react like a person would, not a survey.

Keep replies short (2-4 sentences), ask at most one open question per reply, and never sound \
clinical. You are having a plain conversation — you have no tools and take no actions beyond \
replying here. Write in plain conversational text only — no asterisk-wrapped action \
narration or other roleplay stage directions (e.g. never write things like "*looks up*"), \
since the chat displays your words as plain text, not markdown.

{profile_context}"""


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": {"code": ErrorCode.NOT_FOUND, "message": "Conversation not found"}},
    )


def _gateway_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={
            "error": {
                "code": ErrorCode.INTERNAL_ERROR,
                "message": "Rafiqi is unavailable right now, try again shortly",
            }
        },
    )


def _persona_prompt(student_name: str, cards: list[ProfileCard]) -> str:
    if not cards:
        profile_context = "You don't know this student yet — this is their first visit to the Cave."
    else:
        lines = "\n".join(
            f"- {CARD_DEFINITIONS[CardKey(c.card_key)].title}: {c.reading}" for c in cards
        )
        profile_context = f"What you already know about this student so far:\n{lines}"
    return _PERSONA_SYSTEM_PROMPT.format(student_name=student_name, profile_context=profile_context)


async def _existing_cards(student_id: uuid.UUID, db: AsyncSession) -> list[ProfileCard]:
    profile_result = await db.execute(
        select(StudentProfile).where(StudentProfile.student_id == student_id)
    )
    profile = profile_result.scalar_one_or_none()
    if profile is None:
        return []
    cards_result = await db.execute(
        select(ProfileCard).where(ProfileCard.profile_id == profile.id)
    )
    return list(cards_result.scalars().all())


async def _recent_messages(
    conversation_id: uuid.UUID, db: AsyncSession, limit: int = _HISTORY_LIMIT
) -> list[ConversationMessage]:
    result = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.created_at.desc())
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))


async def _last_message(conversation_id: uuid.UUID, db: AsyncSession) -> ConversationMessage | None:
    result = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _message_count(conversation_id: uuid.UUID, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
    )
    return result.scalar_one()


async def _most_recently_active(
    student_id: uuid.UUID, school_id: uuid.UUID, db: AsyncSession
) -> tuple[Conversation, ConversationMessage] | None:
    """
    The conversation with the single most recent message across this
    student's whole history — not just the most recently *started* one, so
    resuming an old conversation makes it "current" again going forward.
    N+1 queries; fine at the conversation-per-student volumes this product
    expects, revisit with a single query if that stops being true.
    """
    result = await db.execute(
        select(Conversation).where(
            Conversation.student_id == student_id, Conversation.school_id == school_id
        )
    )
    best: tuple[Conversation, ConversationMessage] | None = None
    for conversation in result.scalars().all():
        last = await _last_message(conversation.id, db)
        if last is None:
            continue
        if best is None or last.created_at > best[1].created_at:
            best = (conversation, last)
    return best


async def _maybe_extract(
    conversation: Conversation, db: AsyncSession, *, force: bool = False
) -> list[ProfileCard] | None:
    """
    Runs A3 over whatever's accumulated since this conversation's last
    extraction checkpoint, if there's enough of it (or `force`, used when a
    conversation is going dormant and might never reach the threshold
    otherwise). Returns None when extraction didn't run *or* ran but failed
    (LLM/parse error) — either way there's nothing new to report and the
    checkpoint isn't advanced on failure, so that slice is retried next time.
    """
    total = await _message_count(conversation.id, db)
    unprocessed = total - conversation.last_extracted_message_count
    if unprocessed <= 0 or (not force and unprocessed < _EXTRACTION_TURN_INTERVAL):
        return None

    touched = await profile_extraction.extract_and_merge(
        conversation, db, message_offset=conversation.last_extracted_message_count
    )
    if touched is None:
        return None

    conversation.last_extracted_message_count = total
    await db.commit()
    return touched


async def get_owned_conversation(
    conversation_id: uuid.UUID, student_id: uuid.UUID, school_id: uuid.UUID, db: AsyncSession
) -> Conversation:
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.student_id == student_id,
            Conversation.school_id == school_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise _not_found()
    return conversation


async def list_messages(conversation_id: uuid.UUID, db: AsyncSession) -> list[ConversationMessage]:
    result = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.created_at)
    )
    return list(result.scalars().all())


async def list_conversations(
    student_id: uuid.UUID, school_id: uuid.UUID, db: AsyncSession
) -> list[tuple[Conversation, ConversationMessage | None, bool]]:
    """
    Every conversation this student has ever had, most recently active
    first, each paired with its last message (None if somehow empty) and
    whether it's currently the "active" one — the one a plain
    POST /conversations resumes. Every conversation here is still directly
    resumable by id regardless of this flag; there's no "closed" state.
    """
    result = await db.execute(
        select(Conversation).where(
            Conversation.student_id == student_id, Conversation.school_id == school_id
        )
    )
    conversations = result.scalars().all()

    rows: list[tuple[Conversation, ConversationMessage | None]] = []
    for conversation in conversations:
        rows.append((conversation, await _last_message(conversation.id, db)))

    rows.sort(key=lambda row: row[1].created_at if row[1] else row[0].started_at, reverse=True)

    now = datetime.now(timezone.utc)
    return [
        (
            conversation,
            last,
            i == 0 and last is not None and now - last.created_at < _ACTIVE_WINDOW,
        )
        for i, (conversation, last) in enumerate(rows)
    ]


async def get_active_conversation(
    student_id: uuid.UUID, school_id: uuid.UUID, student_name: str, db: AsyncSession,
    *, force_fresh: bool = False,
) -> tuple[Conversation, ConversationMessage, bool]:
    """
    Returns the student's active conversation: the one with the most recent
    message, if that message is less than `_ACTIVE_WINDOW` old — resumed
    as-is, no new LLM call. Otherwise starts a fresh conversation, first
    force-running extraction on whatever's unprocessed in the old one so a
    short conversation that never reached the 20-turn threshold still isn't
    lost (there's no /end to guarantee that anymore).

    `force_fresh=True` makes a still-active conversation behave like a
    dormant one — used when the student explicitly asks to start over
    rather than continue their current thread. Same force-extract-first
    treatment either way, so an early "start fresh" doesn't reintroduce the
    lost-short-conversation problem this ticket already solved for timeouts.

    Every past conversation stays directly resumable regardless of this
    choice — it only decides what a plain "open the Cave" visit lands on.

    Third return value is `is_new` — False means the caller got back an
    existing conversation's most recent message, not a fresh greeting; the
    frontend should fetch the full history (GET /conversations/{id}) to
    resume rendering it rather than treating `message` as the only content.
    """
    most_recent = await _most_recently_active(student_id, school_id, db)
    if most_recent is not None:
        conversation, last_message = most_recent
        is_within_window = datetime.now(timezone.utc) - last_message.created_at < _ACTIVE_WINDOW
        if is_within_window and not force_fresh:
            return conversation, last_message, False
        await _maybe_extract(conversation, db, force=True)

    conversation = Conversation(id=uuid.uuid4(), school_id=school_id, student_id=student_id)
    db.add(conversation)
    await db.flush()

    cards = await _existing_cards(student_id, db)
    try:
        opening_text = await chat_completion(
            messages=[
                {"role": "system", "content": _persona_prompt(student_name, cards)},
                {
                    "role": "user",
                    "content": "(The student just opened the Cave. Greet them warmly and ask "
                    "your first getting-to-know-you question.)",
                },
            ],
            model=settings.CAVE_CHAT_MODEL,
        )
    except LLMError:
        raise _gateway_unavailable()

    opening = ConversationMessage(
        id=uuid.uuid4(),
        school_id=school_id,
        conversation_id=conversation.id,
        role=MessageRole.RAFIQI,
        content=opening_text,
    )
    db.add(opening)
    await db.commit()
    await db.refresh(conversation)
    await db.refresh(opening)
    return conversation, opening, True


async def post_message(
    conversation: Conversation, student_name: str, content: str, db: AsyncSession
) -> tuple[ConversationMessage, list[ProfileCard] | None]:
    """
    Sends a student message and returns Rafiqi's reply, plus whatever A3
    extraction produced *if* it happened to run on this turn (see
    `_maybe_extract` — roughly every 20 stored messages), else None. Any
    conversation can be posted to at any time, however old — there's no
    "ended" state to block it.
    """
    category = await classify_message(content)

    if category is not None:
        db.add(
            ConversationMessage(
                id=uuid.uuid4(),
                school_id=conversation.school_id,
                conversation_id=conversation.id,
                role=MessageRole.STUDENT,
                content=content,
                flagged=True,
                flag_category=category.value,
            )
        )
        reply = ConversationMessage(
            id=uuid.uuid4(),
            school_id=conversation.school_id,
            conversation_id=conversation.id,
            role=MessageRole.RAFIQI,
            content=SAFETY_SCRIPTS[category],
        )
        db.add(reply)
        await db.commit()
        await db.refresh(reply)
        updated_cards = await _maybe_extract(conversation, db)
        return reply, updated_cards

    db.add(
        ConversationMessage(
            id=uuid.uuid4(),
            school_id=conversation.school_id,
            conversation_id=conversation.id,
            role=MessageRole.STUDENT,
            content=content,
        )
    )
    await db.flush()

    cards = await _existing_cards(conversation.student_id, db)
    history = await _recent_messages(conversation.id, db)
    llm_messages = [{"role": "system", "content": _persona_prompt(student_name, cards)}]
    llm_messages += [
        {"role": "assistant" if msg.role == MessageRole.RAFIQI else "user", "content": msg.content}
        for msg in history
    ]

    try:
        reply_text = await chat_completion(messages=llm_messages, model=settings.CAVE_CHAT_MODEL)
    except LLMError:
        raise _gateway_unavailable()

    reply = ConversationMessage(
        id=uuid.uuid4(),
        school_id=conversation.school_id,
        conversation_id=conversation.id,
        role=MessageRole.RAFIQI,
        content=reply_text,
    )
    db.add(reply)
    await db.commit()
    await db.refresh(reply)

    updated_cards = await _maybe_extract(conversation, db)
    return reply, updated_cards


async def list_flags(school_id: uuid.UUID, db: AsyncSession) -> list[tuple[ConversationMessage, str]]:
    result = await db.execute(
        select(ConversationMessage, User.full_name)
        .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
        .join(User, User.id == Conversation.student_id)
        .where(ConversationMessage.school_id == school_id, ConversationMessage.flagged.is_(True))
        .order_by(ConversationMessage.created_at.desc())
    )
    return [(row[0], row[1]) for row in result.all()]
