"""Inbox access and atomic event/installation operations."""
import hashlib
import uuid
from datetime import datetime, timezone
from cryptography.fernet import Fernet
from sqlalchemy import case, delete, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.models.notifications import Notification, NotificationOutbox, PushInstallation
from app.models.user import User
from app.schemas.notifications import CountOut, DestinationOut, InboxOut, InstallationIn, NotificationOut, ResultOut


class NotificationNotFound(Exception):
    pass


class NotificationUnavailable(Exception):
    pass


def utcnow():
    return datetime.now(timezone.utc)


def token_cipher():
    if not settings.NOTIFICATION_TOKEN_KEY:
        raise NotificationUnavailable()
    return Fernet(settings.NOTIFICATION_TOKEN_KEY.encode())


async def enqueue_assignment_event(db: AsyncSession, school_id: uuid.UUID, assignment_id: uuid.UUID):
    """Caller owns the business transaction; never commit here."""
    if not settings.NOTIFICATION_INBOX_ENABLED:
        return
    await db.execute(insert(NotificationOutbox).values(
        id=uuid.uuid4(), school_id=school_id, event_key=f"material-assigned:{assignment_id}",
        event_type="material_assigned", payload={"assignment_id": str(assignment_id)},
    ).on_conflict_do_nothing(constraint="uq_notification_event"))


def scope(school_id, user_id):
    return (Notification.school_id == school_id, Notification.recipient_id == user_id)


async def list_inbox(db: AsyncSession, school_id, user_id, unread_only=False, cursor=None, limit=30):
    query = select(Notification).where(*scope(school_id, user_id))
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    if cursor:
        stamp, identifier = cursor.split("|", 1)
        query = query.where(tuple_(Notification.created_at, Notification.id) < tuple_(datetime.fromisoformat(stamp), uuid.UUID(identifier)))
    rows = list((await db.scalars(query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit + 1))).all())
    page = rows[:limit]
    next_cursor = f"{page[-1].created_at.isoformat()}|{page[-1].id}" if len(rows) > limit else None
    return InboxOut(items=[NotificationOut.model_validate(row) for row in page], next_cursor=next_cursor, cutoff=utcnow())


async def unread_count(db: AsyncSession, school_id, user_id):
    count = await db.scalar(select(func.count()).select_from(Notification).where(*scope(school_id, user_id), Notification.read_at.is_(None)))
    return CountOut(count=count or 0)


async def mark_read(db: AsyncSession, school_id, user_id, notification_id):
    row = await db.scalar(select(Notification).where(*scope(school_id, user_id), Notification.id == notification_id).with_for_update())
    if row is None:
        raise NotificationNotFound()
    row.read_at = row.read_at or utcnow()
    result = NotificationOut.model_validate(row)
    await db.commit()
    return result


async def mark_all_read(db: AsyncSession, school_id, user_id, cutoff):
    cutoff = min(cutoff, utcnow())
    await db.execute(update(Notification).where(*scope(school_id, user_id), Notification.created_at <= cutoff, Notification.read_at.is_(None)).values(read_at=utcnow()))
    await db.commit()
    return ResultOut()


async def register_installation(db: AsyncSession, school_id, user_id, client_id, body: InstallationIn):
    # Serializes registrations and sending for this account. Token uniqueness
    # is intentionally provider-global: a shared browser has only one owner.
    user = await db.scalar(select(User).where(User.school_id == school_id, User.id == user_id, User.is_active.is_(True)).with_for_update())
    if user is None:
        raise NotificationNotFound()
    fingerprint = hashlib.sha256(body.fid.encode()).hexdigest()
    await db.execute(delete(PushInstallation).where(PushInstallation.school_id == school_id, PushInstallation.user_id == user_id,
        PushInstallation.client_installation_id == client_id, PushInstallation.address_fingerprint != fingerprint))
    ciphertext = token_cipher().encrypt(body.fid.encode()).decode()
    statement = insert(PushInstallation).values(id=uuid.uuid4(), school_id=school_id, user_id=user_id,
        client_installation_id=client_id, address_fingerprint=fingerprint, address_ciphertext=ciphertext, locale=body.locale)
    await db.execute(statement.on_conflict_do_update(index_elements=[PushInstallation.address_fingerprint], set_={
        "school_id": school_id, "user_id": user_id, "client_installation_id": client_id,
        "address_ciphertext": ciphertext, "locale": body.locale, "last_seen_at": utcnow(), "disabled_at": None,
        "binding_version": case((or_(PushInstallation.user_id != user_id,
            PushInstallation.school_id != school_id, PushInstallation.disabled_at.is_not(None)),
            PushInstallation.binding_version + 1), else_=PushInstallation.binding_version),
    }))
    await db.commit()
    return ResultOut()


async def unregister_installation(db: AsyncSession, school_id, user_id, client_id):
    await db.execute(update(PushInstallation).where(PushInstallation.school_id == school_id, PushInstallation.user_id == user_id,
        PushInstallation.client_installation_id == client_id).values(disabled_at=utcnow(), binding_version=PushInstallation.binding_version + 1))
    await db.commit()
    return ResultOut()


async def destination(db: AsyncSession, school_id, user_id, notification_id):
    from app.models.resources import LessonMaterial, TeacherClassStudent, TeacherResource
    row = await db.scalar(select(Notification).where(*scope(school_id, user_id), Notification.id == notification_id))
    if row is None or row.target_type != "material":
        raise NotificationNotFound()
    assignment = await db.scalar(select(LessonMaterial).join(TeacherClassStudent, TeacherClassStudent.class_id == LessonMaterial.class_id)
        .join(TeacherResource, TeacherResource.id == LessonMaterial.resource_id).where(
            LessonMaterial.school_id == school_id, LessonMaterial.id == uuid.UUID(row.target_id),
            TeacherClassStudent.school_id == school_id, TeacherClassStudent.student_id == user_id,
            TeacherResource.school_id == school_id, TeacherResource.archived_at.is_(None)))
    if assignment is None:
        raise NotificationNotFound()
    from urllib.parse import urlencode
    return DestinationOut(path="/student/study-cave?" + urlencode({"lesson_id": assignment.lesson_id, "phase": "before"}))
