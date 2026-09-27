import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db_session, require_student
from app.schemas.profile import StudentProfileViewOut, StudentTraitCardOut, TraitFlagIn, TraitFlagOut
from app.services import profile as profile_svc

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get(
    "/me",
    response_model=StudentProfileViewOut,
    summary="Get my own profile (A6)",
)
async def get_my_profile(
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> StudentProfileViewOut:
    """
    The student's own profile, narrative view only. Per the A6 disclosure
    rule, this never exposes the raw numeric `score` — only the derived
    "confident" / "still_forming" label. Returns an empty card list for a
    student who hasn't chatted in the Cave yet.

    Student access only.
    """
    traits = await profile_svc.get_own_profile_cards(current_user.id, current_user.school_id, db)
    return StudentProfileViewOut(cards=[StudentTraitCardOut.model_validate(t) for t in traits])


@router.post(
    "/traits/{trait_id}/flag",
    response_model=TraitFlagOut,
    summary="Flag a trait card as wrong (A5)",
    responses={404: {"description": "Trait not found."}},
)
async def flag_trait(
    trait_id: uuid.UUID,
    body: TraitFlagIn,
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> TraitFlagOut:
    """
    "Not quite me?" — the student flags one of their own trait cards as wrong
    and explains why. Resolved immediately: Rafiqi re-reads the card against
    the student's explanation and revises it (or, on any failure, conservatively
    resets it to "still forming" rather than leaving it looking unchanged).
    The flag and its outcome are kept as an audit trail either way.

    Student access only, own trait only — 404 for another student's trait.
    """
    trait, acknowledgement = await profile_svc.flag_trait(
        trait_id, current_user.id, current_user.school_id, body.reason, db
    )
    return TraitFlagOut(
        trait=StudentTraitCardOut.model_validate(trait), acknowledgement=acknowledgement
    )
