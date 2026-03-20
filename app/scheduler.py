"""
APScheduler setup for timed bot deployment.
Uses AsyncIOScheduler to integrate with FastAPI's asyncio event loop.
"""

from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

scheduler = AsyncIOScheduler(timezone="UTC")
_subscription_id: str | None = None


def set_subscription_id(sub_id: str) -> None:
    """Store the Graph subscription ID and schedule periodic renewal."""
    global _subscription_id
    _subscription_id = sub_id
    scheduler.add_job(
        _renew_subscription_job,
        trigger=IntervalTrigger(hours=60),
        id="graph_subscription_renewal",
        replace_existing=True,
    )


async def _renew_subscription_job() -> None:
    global _subscription_id
    if not _subscription_id:
        return
    from app.services.graph_service import renew_calendar_subscription
    try:
        result = await renew_calendar_subscription(_subscription_id)
        print(f"[Scheduler] Graph subscription renewed, expires {result['expirationDateTime']}")
    except Exception as e:
        print(f"[Scheduler] Failed to renew subscription: {e}")


async def _deploy_bot_job(scheduled_meeting_id: int, org_id: int, join_url: str, subject: str) -> None:
    """APScheduler job: deploy a Recall.ai bot for a scheduled meeting."""
    from app.database import SessionLocal
    from app.models import BotSession, ScheduledMeeting
    from app.services.recall_service import create_bot
    from app.config import settings

    print(f"[Scheduler] Deploying bot for ScheduledMeeting id={scheduled_meeting_id}")
    db = SessionLocal()
    sched = None
    try:
        sched = db.query(ScheduledMeeting).filter_by(id=scheduled_meeting_id).first()
        if not sched or sched.status != "scheduled":
            print(f"[Scheduler] Skipping — status={sched.status if sched else 'not found'}")
            return

        webhook_url = None
        if settings.WEBHOOK_BASE_URL:
            webhook_url = f"{settings.WEBHOOK_BASE_URL.rstrip('/')}/recall/webhook"

        bot_data = await create_bot(
            meeting_url=join_url,
            bot_name="AI Meeting Assistant",
            webhook_url=webhook_url,
        )
        bot_id = bot_data["id"]

        session = BotSession(
            org_id=org_id,
            bot_id=bot_id,
            meeting_url=join_url,
            meeting_name=subject or "Teams Meeting",
            status="created",
        )
        db.add(session)
        db.flush()

        sched.bot_session_id = session.id
        sched.status = "completed"
        db.commit()
        print(f"[Scheduler] Bot {bot_id} dispatched for ScheduledMeeting id={scheduled_meeting_id}")
    except Exception as e:
        import traceback
        print(f"[Scheduler] Error deploying bot: {e}")
        traceback.print_exc()
        if sched:
            sched.status = "failed"
            db.commit()
    finally:
        db.close()


def schedule_bot_deployment(scheduled_meeting_id: int, org_id: int, join_url: str,
                             subject: str, start_time: datetime) -> str:
    """Schedule bot deployment at start_time - 1 minute. Returns the job ID."""
    fire_at = start_time - timedelta(minutes=1)
    now = datetime.now(timezone.utc)

    if fire_at.tzinfo is None:
        fire_at = fire_at.replace(tzinfo=timezone.utc)

    if fire_at <= now:
        fire_at = now + timedelta(seconds=5)

    job_id = f"bot_deploy_{scheduled_meeting_id}"
    scheduler.add_job(
        _deploy_bot_job,
        trigger=DateTrigger(run_date=fire_at),
        id=job_id,
        replace_existing=True,
        kwargs={
            "scheduled_meeting_id": scheduled_meeting_id,
            "org_id": org_id,
            "join_url": join_url,
            "subject": subject,
        },
    )
    print(f"[Scheduler] Job {job_id} scheduled for {fire_at.isoformat()}")
    return job_id


from app.services.bot_processing_service import DONE_STATUSES as _POLL_DONE_STATUSES


async def _poll_pending_bots_job() -> None:
    """Every 2 minutes: check for bot sessions that completed but missed the webhook."""
    from app.database import SessionLocal
    from app.models import BotSession
    from app.services.recall_service import get_bot
    from app.services.bot_processing_service import process_bot_session
    from datetime import timedelta

    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        pending = (
            db.query(BotSession)
            .filter(
                BotSession.status.notin_(["done", "failed", "processing"]),
                BotSession.meeting_id.is_(None),
                BotSession.created_at > cutoff.replace(tzinfo=None),
            )
            .all()
        )
        if not pending:
            return

        print(f"[Poller] Checking {len(pending)} pending bot session(s)...")
        for session in pending:
            bot_id = session.bot_id
            org_id = session.org_id
            try:
                bot_data = await get_bot(bot_id)
                status_changes = bot_data.get("status_changes", [])
                recall_status = (
                    status_changes[-1].get("code", "unknown")
                    if status_changes
                    else bot_data.get("status", "unknown")
                )
                if recall_status in _POLL_DONE_STATUSES:
                    print(f"[Poller] Bot {bot_id} is done — triggering processing")
                    session.status = "processing"
                    db.commit()
                    db.close()
                    db = SessionLocal()
                    await process_bot_session(bot_id, org_id)
            except Exception as e:
                print(f"[Poller] Error checking bot {bot_id}: {e}")
    finally:
        db.close()


def reschedule_pending_on_startup() -> None:
    """Re-create APScheduler jobs for pending meetings after an app restart."""
    from app.database import SessionLocal
    from app.models import ScheduledMeeting

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        pending = (
            db.query(ScheduledMeeting)
            .filter(ScheduledMeeting.status == "scheduled")
            .filter(ScheduledMeeting.start_time > now.replace(tzinfo=None))
            .all()
        )
        print(f"[Scheduler] Rescheduling {len(pending)} pending meetings on startup.")
        for sched in pending:
            start_utc = sched.start_time.replace(tzinfo=timezone.utc)
            schedule_bot_deployment(
                scheduled_meeting_id=sched.id,
                org_id=sched.org_id,
                join_url=sched.join_url,
                subject=sched.subject,
                start_time=start_utc,
            )
    finally:
        db.close()
