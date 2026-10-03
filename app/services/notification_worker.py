"""Bounded PostgreSQL outbox fan-out and Firebase delivery."""
import asyncio
import logging
import random
import uuid
from datetime import timedelta
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.notifications import Notification, NotificationDelivery, NotificationOutbox, PushInstallation
from app.models.resources import LessonMaterial, TeacherClassStudent, TeacherResource
from app.models.user import User
from app.services.notifications import token_cipher, utcnow

logger = logging.getLogger(__name__)


async def expand_one(db):
    event = await db.scalar(select(NotificationOutbox).where(NotificationOutbox.status == "pending", NotificationOutbox.available_at <= utcnow())
        .order_by(NotificationOutbox.created_at).with_for_update(skip_locked=True).limit(1))
    if event is None:
        return False
    if event.event_type != "material_assigned" or event.payload_version != 1:
        event.status = "failed"
        await db.commit()
        return True
    try:
        assignment_id = uuid.UUID(event.payload["assignment_id"])
    except (KeyError, ValueError, TypeError):
        event.status = "failed"
        await db.commit()
        return True
    assignment = await db.scalar(select(LessonMaterial).where(LessonMaterial.school_id == event.school_id,
        LessonMaterial.id == assignment_id))
    if assignment is None:
        event.status = "cancelled"
        await db.commit()
        return True
    resource = await db.scalar(select(TeacherResource).where(TeacherResource.school_id == event.school_id,
        TeacherResource.id == assignment.resource_id, TeacherResource.archived_at.is_(None)))
    source = await db.scalar(select(User.full_name).where(User.school_id == event.school_id, User.id == assignment.added_by))
    if resource is None:
        event.status = "cancelled"
        await db.commit()
        return True
    query = select(User.id).join(TeacherClassStudent, TeacherClassStudent.student_id == User.id).where(
        User.school_id == event.school_id, User.is_active.is_(True), TeacherClassStudent.school_id == event.school_id,
        TeacherClassStudent.class_id == assignment.class_id)
    if event.recipient_cursor:
        query = query.where(User.id > uuid.UUID(event.recipient_cursor))
    recipients = list((await db.scalars(query.order_by(User.id).limit(100))).all())
    for recipient in recipients:
        notification_id = uuid.uuid4()
        result = await db.execute(insert(Notification).values(id=notification_id, school_id=event.school_id,
            recipient_id=recipient, outbox_event_id=event.id, template_key="materialAssigned",
            template_data={"title": resource.title, "source": source or "Rafiqi"}, target_type="material", target_id=str(assignment.id))
            .on_conflict_do_nothing(constraint="uq_notification_recipient").returning(Notification.id))
        if result.scalar_one_or_none() is not None and settings.NOTIFICATION_PUSH_ENABLED:
            installations = (await db.scalars(select(PushInstallation).where(PushInstallation.school_id == event.school_id,
                PushInstallation.user_id == recipient, PushInstallation.disabled_at.is_(None),
                PushInstallation.last_seen_at > utcnow() - timedelta(days=30)))).all()
            for installation in installations:
                db.add(NotificationDelivery(school_id=event.school_id, notification_id=notification_id,
                    installation_id=installation.id, binding_version=installation.binding_version))
    if recipients:
        event.recipient_cursor = str(recipients[-1])
    if len(recipients) < 100:
        event.status = "processed"
    await db.commit()
    return True


def retry_delay(attempt):
    return min(3600, 60 * 2 ** min(attempt - 1, 6)) + random.randint(0, 30)


async def firebase_send(token, locale, notification_id):
    import firebase_admin
    from firebase_admin import messaging
    try:
        app = firebase_admin.get_app("notifications")
    except ValueError:
        from firebase_admin import credentials
        credential = credentials.Certificate(settings.GOOGLE_APPLICATION_CREDENTIALS) if settings.GOOGLE_APPLICATION_CREDENTIALS else None
        app = firebase_admin.initialize_app(credential, options={"projectId": settings.FIREBASE_PROJECT_ID, "httpTimeout": 20}, name="notifications")
    title = "رفيقي" if locale == "ar" else "Rafiqi"
    body = "لديك تحديث جديد في رفيقي" if locale == "ar" else "You have a new update in Rafiqi."
    # Only a generic inbox URL leaves the trusted server; no private target data.
    link = f"{settings.NOTIFICATION_WEB_ORIGIN.rstrip('/')}/{locale}/student/notifications?open={notification_id}"
    message = messaging.Message(fid=token, notification=messaging.Notification(title=title, body=body),
        data={"notification_id": str(notification_id)}, webpush=messaging.WebpushConfig(
            headers={"TTL": "3600"}, notification=messaging.WebpushNotification(tag=f"rafiqi-{notification_id}"),
            fcm_options=messaging.WebpushFCMOptions(link=link) if link.startswith("https://") else None))
    response = await messaging.send_each_async([message], app=app)
    result = response.responses[0]
    if result.exception:
        raise result.exception
    return result.message_id


async def deliver_one(db, sender=firebase_send):
    delivery = await db.scalar(select(NotificationDelivery).where(NotificationDelivery.status == "pending",
        NotificationDelivery.next_attempt_at <= utcnow()).order_by(NotificationDelivery.next_attempt_at)
        .with_for_update(skip_locked=True).limit(1))
    if delivery is None:
        return False
    notification = await db.scalar(select(Notification).where(Notification.school_id == delivery.school_id,
        Notification.id == delivery.notification_id))
    # One account lock serializes rate reservation across worker processes.
    user = await db.scalar(select(User).where(User.school_id == delivery.school_id, User.id == notification.recipient_id).with_for_update())
    installation = await db.scalar(select(PushInstallation).where(PushInstallation.school_id == delivery.school_id,
        PushInstallation.id == delivery.installation_id, PushInstallation.user_id == notification.recipient_id).with_for_update())
    now = utcnow()
    if not user or not user.is_active or not installation or installation.disabled_at or installation.binding_version != delivery.binding_version or (
        notification.expires_at and notification.expires_at <= now):
        delivery.status = "cancelled"
    elif notification.push_suppressed_at:
        delivery.status = "suppressed"
    else:
        if notification.push_reserved_at is None:
            count = await db.scalar(select(func.count()).select_from(Notification).where(Notification.school_id == delivery.school_id,
                Notification.recipient_id == notification.recipient_id,
                Notification.push_reserved_at > now - timedelta(seconds=settings.NOTIFICATION_PUSH_WINDOW_SECONDS)))
            if count >= settings.NOTIFICATION_PUSH_LIMIT:
                notification.push_suppressed_at = now
                delivery.status = "suppressed"
            else:
                notification.push_reserved_at = now
        if delivery.status == "pending":
            delivery.attempt_count += 1
            delivery.lease_expires_at = now + timedelta(seconds=60)
            try:
                token = token_cipher().decrypt(installation.address_ciphertext.encode()).decode()
                delivery.provider_message_id = await asyncio.wait_for(sender(token, installation.locale, notification.id), timeout=25)
                delivery.accepted_at = utcnow()
                delivery.status = "accepted"
            except Exception as exc:
                from firebase_admin import exceptions, messaging
                delivery.last_error_code = type(exc).__name__[:80]
                if isinstance(exc, messaging.UnregisteredError):
                    installation.disabled_at = now
                    delivery.status = "invalid"
                elif isinstance(exc, (exceptions.InvalidArgumentError, exceptions.PermissionDeniedError)) or delivery.attempt_count >= 6:
                    delivery.status = "failed"
                else:
                    delay = retry_delay(delivery.attempt_count)
                    response = getattr(exc, "http_response", None)
                    retry_after = response.headers.get("Retry-After", "") if response is not None else ""
                    if retry_after.isdigit():
                        delay = max(delay, int(retry_after))
                    delivery.next_attempt_at = now + timedelta(seconds=delay)
            delivery.lease_expires_at = None
    # Holding row locks through the bounded send prevents concurrent rebinding.
    # A crash rolls back and releases locks; the same stable tag limits duplicates.
    await db.commit()
    return True


async def run():
    logging.basicConfig(level=logging.INFO)
    if settings.NOTIFICATION_PUSH_ENABLED:
        token_cipher()
    while True:
        try:
            async with AsyncSessionLocal() as db:
                expanded = await expand_one(db)
                delivered = await deliver_one(db) if settings.NOTIFICATION_PUSH_ENABLED else False
            if not expanded and not delivered:
                await asyncio.sleep(2)
        except Exception:
            logger.exception("Notification worker iteration failed")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run())
