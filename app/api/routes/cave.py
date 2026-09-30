import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db_session, require_student, require_teacher
from app.schemas.cave import (
    CaveConversationOut,
    CaveMessageIn,
    CaveMessageOut,
    ConversationStartOut,
    ConversationSummaryOut,
    FlaggedMessageOut,
    SendMessageOut,
)
from app.schemas.profile import StudentTraitCardOut
from app.services import cave as cave_svc
from app.services import user as user_svc

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post(
    "",
    response_model=ConversationStartOut,
    status_code=200,
    summary="Start or resume the active Cave chat",
    responses={502: {"description": "Rafiqi is unavailable right now."}},
)
async def start_conversation(
    response: Response,
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> ConversationStartOut:
    """
    Returns the student's active conversation if one exists — the one with
    a message less than 12h old — resumed as-is (fetch GET
    /conversations/{id} for its full history). Otherwise starts a fresh one
    and returns Rafiqi's opening message (`is_new: true`, `201`).

    Every conversation stays individually resumable at any time regardless
    (see GET /conversations, POST /conversations/{id}/messages) — this only
    decides what a plain "open the Cave" visit lands on. A dormant
    conversation left behind by this call has any unprocessed messages
    swept into a profile update first, so nothing from it is lost.

    Student access only.
    """
    student = await user_svc.get_me(current_user.id, db)
    conversation, message, is_new = await cave_svc.get_active_conversation(
        current_user.id, current_user.school_id, student.full_name, db
    )
    response.status_code = status.HTTP_201_CREATED if is_new else status.HTTP_200_OK
    return ConversationStartOut(
        conversation_id=conversation.id,
        message=CaveMessageOut.model_validate(message),
        is_new=is_new,
    )


@router.get(
    "",
    response_model=list[ConversationSummaryOut],
    summary="List my conversations",
)
async def list_conversations(
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> list[ConversationSummaryOut]:
    """
    Every conversation this student has ever had, most recently active
    first, so they can browse and resume any past one — not just the
    current active thread. Student access only.
    """
    rows = await cave_svc.list_conversations(current_user.id, current_user.school_id, db)
    return [
        ConversationSummaryOut(
            id=conversation.id,
            started_at=conversation.started_at,
            last_message_at=last.created_at,
            last_message_preview=last.content[:140],
            is_active=is_active,
        )
        for conversation, last, is_active in rows
        if last is not None  # a conversation with zero messages shouldn't exist, but guard anyway
    ]


@router.get(
    "/flags",
    response_model=list[FlaggedMessageOut],
    summary="List flagged Cave messages",
    responses={403: {"description": "Teacher access required."}},
)
async def list_flags(
    current_user: Annotated[CurrentUser, Depends(require_teacher)],
    db: AsyncSession = Depends(get_db_session),
) -> list[FlaggedMessageOut]:
    """
    Lists every message the safety classifier has flagged (self-harm, abuse,
    bullying, distress, cheating) for students in the teacher's school, most
    recent first. This is the minimal read path for the safety layer — no
    notifications are sent yet, a teacher must check this list.

    Teacher access only.
    """
    rows = await cave_svc.list_flags(current_user.school_id, db)
    return [
        FlaggedMessageOut(
            id=message.id,
            conversation_id=message.conversation_id,
            student_name=student_name,
            category=message.flag_category,
            content=message.content,
            created_at=message.created_at,
        )
        for message, student_name in rows
    ]


@router.post(
    "/{conversation_id}/messages",
    response_model=SendMessageOut,
    summary="Send a message in the Cave",
    responses={
        404: {"description": "Conversation not found."},
        502: {"description": "Rafiqi is unavailable right now."},
    },
)
async def post_message(
    conversation_id: uuid.UUID,
    body: CaveMessageIn,
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> SendMessageOut:
    """
    Sends a student message and returns Rafiqi's reply. Works on any of the
    student's conversations at any time, however old — there's no "ended"
    state.

    Every message is run through a deterministic safety classifier first. If
    it's flagged (self-harm, abuse, bullying, distress, or cheating), the
    message is stored flagged and a fixed scripted reply is returned instead
    of a model-generated one — the chat model is never called for a flagged
    turn.

    Profile extraction (A3) runs automatically roughly every 20 messages in
    a conversation — `updated_traits` is populated only on the turn that
    happens to trigger it, null otherwise.

    Student access only, own conversation only.
    """
    student = await user_svc.get_me(current_user.id, db)
    conversation = await cave_svc.get_owned_conversation(
        conversation_id, current_user.id, current_user.school_id, db
    )
    reply, updated_traits = await cave_svc.post_message(conversation, student.full_name, body.content, db)
    return SendMessageOut(
        message=CaveMessageOut.model_validate(reply),
        updated_traits=(
            [StudentTraitCardOut.model_validate(t) for t in updated_traits]
            if updated_traits is not None
            else None
        ),
    )


@router.get(
    "/{conversation_id}",
    response_model=CaveConversationOut,
    summary="Get a Cave conversation",
    responses={404: {"description": "Conversation not found."}},
)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> CaveConversationOut:
    """
    Fetches a conversation and its full message history, for resuming a chat
    — any conversation of the student's, not just the active one.
    Student access only, own conversation only.
    """
    conversation = await cave_svc.get_owned_conversation(
        conversation_id, current_user.id, current_user.school_id, db
    )
    messages = await cave_svc.list_messages(conversation_id, db)
    return CaveConversationOut(
        id=conversation.id,
        student_id=conversation.student_id,
        school_id=conversation.school_id,
        started_at=conversation.started_at,
        messages=[CaveMessageOut.model_validate(m) for m in messages],
    )
