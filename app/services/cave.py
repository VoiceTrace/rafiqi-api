import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ErrorCode
from app.models.conversation import Conversation
from app.models.message import ConversationMessage, MessageRole
from app.models.profile import ProfileTrait, StudentProfile
from app.models.user import User
from app.services import profile_extraction
from app.services.llm import LLMError, chat_completion
from app.services.safety import SAFETY_SCRIPTS, classify_message

_HISTORY_LIMIT = 12

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


def _already_ended() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": {"code": ErrorCode.VALIDATION_ERROR, "message": "Conversation already ended"}},
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


def _persona_prompt(student_name: str, traits: list[ProfileTrait]) -> str:
    if not traits:
        profile_context = "You don't know this student yet — this is their first visit to the Cave."
    else:
        lines = "\n".join(f"- {t.title}: {t.description}" for t in traits)
        profile_context = f"What you already know about this student so far:\n{lines}"
    return _PERSONA_SYSTEM_PROMPT.format(student_name=student_name, profile_context=profile_context)


async def _existing_traits(student_id: uuid.UUID, db: AsyncSession) -> list[ProfileTrait]:
    profile_result = await db.execute(
        select(StudentProfile).where(StudentProfile.student_id == student_id)
    )
    profile = profile_result.scalar_one_or_none()
    if profile is None:
        return []
    traits_result = await db.execute(
        select(ProfileTrait).where(ProfileTrait.profile_id == profile.id)
    )
    return list(traits_result.scalars().all())


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


async def start_conversation(
    student_id: uuid.UUID, school_id: uuid.UUID, student_name: str, db: AsyncSession
) -> tuple[Conversation, ConversationMessage]:
    conversation = Conversation(id=uuid.uuid4(), school_id=school_id, student_id=student_id)
    db.add(conversation)
    await db.flush()

    traits = await _existing_traits(student_id, db)
    try:
        opening_text = await chat_completion(
            messages=[
                {"role": "system", "content": _persona_prompt(student_name, traits)},
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
    return conversation, opening


async def post_message(
    conversation: Conversation, student_name: str, content: str, db: AsyncSession
) -> ConversationMessage:
    if conversation.ended_at is not None:
        raise _already_ended()

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
        return reply

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

    traits = await _existing_traits(conversation.student_id, db)
    history = await _recent_messages(conversation.id, db)
    llm_messages = [{"role": "system", "content": _persona_prompt(student_name, traits)}]
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
    return reply


async def end_conversation(conversation: Conversation, db: AsyncSession) -> None:
    if conversation.ended_at is not None:
        raise _already_ended()
    conversation.ended_at = datetime.now(timezone.utc)
    await db.commit()
    await profile_extraction.extract_and_merge(conversation, db)


async def list_flags(school_id: uuid.UUID, db: AsyncSession) -> list[tuple[ConversationMessage, str]]:
    result = await db.execute(
        select(ConversationMessage, User.full_name)
        .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
        .join(User, User.id == Conversation.student_id)
        .where(ConversationMessage.school_id == school_id, ConversationMessage.flagged.is_(True))
        .order_by(ConversationMessage.created_at.desc())
    )
    return [(row[0], row[1]) for row in result.all()]
