import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db_session, require_student, require_teacher
from app.schemas.cave import (
    CaveConversationOut,
    CaveMessageIn,
    CaveMessageOut,
    ConversationEndOut,
    ConversationStartOut,
    FlaggedMessageOut,
)
from app.schemas.profile import StudentTraitCardOut
from app.services import cave as cave_svc
from app.services import user as user_svc

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post(
    "",
    response_model=ConversationStartOut,
    status_code=201,
    summary="Start a Cave chat",
    responses={502: {"description": "Rafiqi is unavailable right now."}},
)
async def start_conversation(
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> ConversationStartOut:
    """
    Starts a new Rafiqi's Cave conversation (A2) and returns Rafiqi's opening
    message. Student access only.
    """
    student = await user_svc.get_me(current_user.id, db)
    conversation, opening = await cave_svc.start_conversation(
        current_user.id, current_user.school_id, student.full_name, db
    )
    return ConversationStartOut(
        conversation_id=conversation.id, message=CaveMessageOut.model_validate(opening)
    )


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
    response_model=CaveMessageOut,
    summary="Send a message in the Cave",
    responses={
        404: {"description": "Conversation not found."},
        400: {"description": "Conversation already ended."},
        502: {"description": "Rafiqi is unavailable right now."},
    },
)
async def post_message(
    conversation_id: uuid.UUID,
    body: CaveMessageIn,
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> CaveMessageOut:
    """
    Sends a student message and returns Rafiqi's reply.

    Every message is run through a deterministic safety classifier first. If
    it's flagged (self-harm, abuse, bullying, distress, or cheating), the
    message is stored flagged and a fixed scripted reply is returned instead
    of a model-generated one — the chat model is never called for a flagged
    turn. Student access only, own conversation only.
    """
    student = await user_svc.get_me(current_user.id, db)
    conversation = await cave_svc.get_owned_conversation(
        conversation_id, current_user.id, current_user.school_id, db
    )
    reply = await cave_svc.post_message(conversation, student.full_name, body.content, db)
    return CaveMessageOut.model_validate(reply)


@router.post(
    "/{conversation_id}/end",
    response_model=ConversationEndOut,
    summary="End a Cave chat",
    responses={
        404: {"description": "Conversation not found."},
        400: {"description": "Conversation already ended."},
    },
)
async def end_conversation(
    conversation_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> ConversationEndOut:
    """
    Ends the conversation and runs profile extraction (A3) against its
    transcript, merging observations into the student's profile traits.
    Returns exactly what changed from *this* conversation — `updated_traits`
    is empty if it gave no real signal (e.g. very short, or everything said
    was safety-flagged and excluded). For the student's whole profile, use
    GET /profiles/me instead.

    Student access only, own conversation only.
    """
    conversation = await cave_svc.get_owned_conversation(
        conversation_id, current_user.id, current_user.school_id, db
    )
    touched = await cave_svc.end_conversation(conversation, db)
    return ConversationEndOut(
        updated_traits=[StudentTraitCardOut.model_validate(t) for t in touched]
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
    Fetches a conversation and its full message history, for resuming a chat.
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
        ended_at=conversation.ended_at,
        messages=[CaveMessageOut.model_validate(m) for m in messages],
    )
