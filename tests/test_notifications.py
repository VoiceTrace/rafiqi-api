"""Real PostgreSQL tests in an isolated schema; never delete application rows."""
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.core.config import settings
from app.core.database import Base
from app.models import School, User
from app.models.notifications import Notification, NotificationDelivery, NotificationOutbox, PushInstallation
from app.models.resources import LessonMaterial, TeacherClass, TeacherClassStudent, TeacherResource
from app.services import notifications as svc
from app.services.notification_worker import deliver_one, expand_one
from app.services.review_catalog import seed_catalog
from app.schemas.notifications import InstallationIn


@pytest_asyncio.fixture
async def store(monkeypatch):
    schema = "notification_test_" + uuid.uuid4().hex
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        await connection.run_sync(Base.metadata.create_all)
    isolated = create_async_engine(settings.DATABASE_URL, connect_args={"server_settings": {"search_path": schema}})
    factory = async_sessionmaker(isolated, expire_on_commit=False)
    monkeypatch.setattr(settings, "NOTIFICATION_TOKEN_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "NOTIFICATION_PUSH_ENABLED", True)
    try:
        async with factory() as db:
            school, other_school = uuid.uuid4(), uuid.uuid4()
            teacher, student, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            db.add_all([School(id=school, name="Notification tests"), School(id=other_school, name="Other")])
            await db.flush()
            for identifier, scope, role in [(teacher, school, "teacher"), (student, school, "student"), (other, other_school, "student")]:
                db.add(User(id=identifier, school_id=scope, email=f"{identifier}@example.test", full_name="Test", role=role, hashed_password="unused"))
            await seed_catalog(db)
            await db.commit()
        yield factory, school, other_school, teacher, student, other
    finally:
        await isolated.dispose()
        async with engine.begin() as connection:
            # The literal name was generated above and stays inside this test schema.
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


async def event_notification(db, school, student, index=0):
    event = NotificationOutbox(school_id=school, event_key=f"test:{index}", event_type="material_assigned", payload={})
    db.add(event)
    await db.flush()
    row = Notification(school_id=school, recipient_id=student, outbox_event_id=event.id,
        template_key="materialAssigned", template_data={"title": "Test", "source": "Teacher"}, target_type="material", target_id=str(uuid.uuid4()))
    db.add(row)
    await db.flush()
    return row


@pytest.mark.asyncio
async def test_inbox_ownership_and_read_cutoff(store):
    factory, school, other_school, _, student, other = store
    async with factory() as db:
        row = await event_notification(db, school, student)
        await db.commit()
        assert (await svc.unread_count(db, school, student)).count == 1
        assert (await svc.list_inbox(db, other_school, other)).items == []
        with pytest.raises(svc.NotificationNotFound):
            await svc.mark_read(db, other_school, other, row.id)
        await svc.mark_all_read(db, school, student, row.created_at - timedelta(seconds=1))
        assert (await svc.unread_count(db, school, student)).count == 1
        await svc.mark_read(db, school, student, row.id)
        await svc.mark_read(db, school, student, row.id)
        assert (await svc.unread_count(db, school, student)).count == 0


@pytest.mark.asyncio
async def test_atomic_rebinding_invalidates_queued_delivery(store):
    factory, school, other_school, _, student, other = store
    fid = "c" + "a" * 21
    async with factory() as db:
        await svc.register_installation(db, school, student, uuid.uuid4(), InstallationIn(fid=fid))
        installation = await db.scalar(select(PushInstallation).where(PushInstallation.school_id == school))
        version = installation.binding_version
        row = await event_notification(db, school, student)
        delivery = NotificationDelivery(school_id=school, notification_id=row.id, installation_id=installation.id, binding_version=version)
        db.add(delivery); await db.commit()
        await svc.register_installation(db, other_school, other, uuid.uuid4(), InstallationIn(fid=fid))
        await db.refresh(installation)
        assert installation.user_id == other
        assert installation.binding_version > version
        assert fid not in installation.address_ciphertext
        sender = AsyncMock(return_value="message")
        await deliver_one(db, sender)
        sender.assert_not_called()
        assert delivery.status == "cancelled"


@pytest.mark.asyncio
async def test_ten_notifications_shared_across_devices_and_inbox_keeps_excess(store):
    factory, school, _, _, student, _ = store
    async with factory() as db:
        for index in range(2):
            await svc.register_installation(db, school, student, uuid.uuid4(), InstallationIn(fid="c" + str(index) * 21))
        installations = list((await db.scalars(select(PushInstallation).where(PushInstallation.school_id == school))).all())
        for index in range(11):
            row = await event_notification(db, school, student, index)
            for device in installations:
                db.add(NotificationDelivery(school_id=school, notification_id=row.id, installation_id=device.id, binding_version=device.binding_version))
        await db.commit()
        sender = AsyncMock(return_value="message")
        while await deliver_one(db, sender):
            pass
        assert sender.await_count == 20
        assert (await svc.unread_count(db, school, student)).count == 11
        assert await db.scalar(select(func.count()).select_from(NotificationDelivery).where(NotificationDelivery.school_id == school, NotificationDelivery.status == "suppressed")) == 2


@pytest.mark.asyncio
async def test_assignment_outbox_commit_rollback_and_fanout(store):
    factory, school, _, teacher, student, _ = store
    async with factory() as db:
        assignment_id = uuid.uuid4()
        await svc.enqueue_assignment_event(db, school, assignment_id)
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(NotificationOutbox).where(NotificationOutbox.school_id == school)) == 0
        cls = TeacherClass(school_id=school, teacher_id=teacher, grade_id="grade-10", name="Test")
        resource = TeacherResource(school_id=school, created_by=teacher, type="article", title="Resource")
        db.add_all([cls, resource]); await db.flush()
        db.add(TeacherClassStudent(school_id=school, class_id=cls.id, student_id=student))
        assignment = LessonMaterial(id=assignment_id, school_id=school, class_id=cls.id, resource_id=resource.id, lesson_id="newton-third-law", added_by=teacher)
        db.add(assignment); await db.flush()
        await svc.enqueue_assignment_event(db, school, assignment_id)
        await svc.enqueue_assignment_event(db, school, assignment_id)
        await db.commit()
        assert await expand_one(db)
        assert not await expand_one(db)
        assert (await svc.unread_count(db, school, student)).count == 1
        row = (await svc.list_inbox(db, school, student)).items[0]
        assert "lesson_id=newton-third-law" in (await svc.destination(db, school, student, row.id)).path


@pytest.mark.asyncio
async def test_registration_refresh_preserves_pending_binding_and_retry(store):
    factory, school, _, _, student, _ = store
    async with factory() as db:
        client_id = uuid.uuid4()
        body = InstallationIn(fid="c" + "b" * 21)
        await svc.register_installation(db, school, student, client_id, body)
        device = await db.scalar(select(PushInstallation).where(PushInstallation.school_id == school))
        version = device.binding_version
        await svc.register_installation(db, school, student, client_id, body)
        await db.refresh(device)
        assert device.binding_version == version
        row = await event_notification(db, school, student)
        delivery = NotificationDelivery(school_id=school, notification_id=row.id, installation_id=device.id, binding_version=version)
        db.add(delivery); await db.commit()
        failed = AsyncMock(side_effect=RuntimeError("temporary"))
        await deliver_one(db, failed)
        assert delivery.status == "pending" and delivery.attempt_count == 1
        assert delivery.next_attempt_at > svc.utcnow()
        assert row.push_reserved_at is not None
        delivery.next_attempt_at = svc.utcnow() - timedelta(seconds=1)
        await db.commit()
        await deliver_one(db, AsyncMock(return_value="accepted"))
        assert delivery.status == "accepted" and delivery.attempt_count == 2
        assert delivery.accepted_at is not None
