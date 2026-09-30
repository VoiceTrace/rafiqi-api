from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db_session, require_student
from app.schemas.profile import CardFlagIn, CardFlagOut, ProfileViewOut
from app.services import profile as profile_svc

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get(
    "/me",
    response_model=ProfileViewOut,
    summary="Get my own learner profile (A6)",
)
async def get_my_profile(
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> ProfileViewOut:
    """
    The student's own learner profile — always exactly the 7 fixed cards
    (How you learn, Where you are, What drives you, How you feel, Your
    study habits, Language & company, Your world), each with a `reading`
    that's null until something real has been extracted for it. Per the A6
    disclosure rule, no numeric score or confidence label is ever included.

    Student access only.
    """
    learner_model = await profile_svc.get_own_profile_view(current_user.id, current_user.school_id, db)
    return ProfileViewOut(learner_model=learner_model)


@router.post(
    "/cards/{card_id}/flag",
    response_model=CardFlagOut,
    summary="Flag a card's reading as wrong (A5)",
    responses={404: {"description": "Card not found — invalid id, or nothing extracted for it yet."}},
)
async def flag_card(
    card_id: int,
    body: CardFlagIn,
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> CardFlagOut:
    """
    "Not quite me?" — the student flags one of their own cards (by its
    fixed 1-7 id, as returned from GET /profiles/me) as wrong and explains
    why. Resolved immediately: Rafiqi re-reads it against their explanation
    and revises it (or, on any failure, conservatively lowers its internal
    confidence rather than leaving it looking unchanged). The flag and its
    outcome are kept as an audit trail either way.

    Student access only, own card only — 404 for another student's card,
    an invalid id, or a card with nothing extracted for it yet (nothing to
    dispute).
    """
    card, acknowledgement = await profile_svc.flag_card(
        card_id, current_user.id, current_user.school_id, body.reason, db
    )
    return CardFlagOut(card=card, acknowledgement=acknowledgement)
