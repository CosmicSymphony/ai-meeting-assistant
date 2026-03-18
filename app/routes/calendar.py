"""
Microsoft Graph calendar webhook routes.
Handles subscription validation, incoming calendar notifications, and manual subscription setup.
"""

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import PlainTextResponse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings
from app.database import SessionLocal
from app.models import ScheduledMeeting
from app.services.graph_service import get_event, accept_event, extract_join_url
from app.scheduler import schedule_bot_deployment

router = APIRouter()

# Windows timezone name → IANA mapping
_TZ_MAP = {
    "UTC": "UTC",
    "Singapore Standard Time": "Asia/Singapore",
    "Malay Peninsula Standard Time": "Asia/Kuala_Lumpur",
    "GMT Standard Time": "Europe/London",
    "Eastern Standard Time": "America/New_York",
    "Central Standard Time": "America/Chicago",
    "Pacific Standard Time": "America/Los_Angeles",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "China Standard Time": "Asia/Shanghai",
    "Tokyo Standard Time": "Asia/Tokyo",
    "India Standard Time": "Asia/Kolkata",
    "Arab Standard Time": "Asia/Riyadh",
    "W. Europe Standard Time": "Europe/Berlin",
}


@router.post("/webhook")
async def graph_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    validationToken: str = None,
):
    """
    Receives Microsoft Graph calendar change notifications.
    Also handles the subscription validation handshake (validationToken query param).
    """
    # Subscription validation handshake — must respond within 10 seconds
    if validationToken:
        return PlainTextResponse(content=validationToken, status_code=200)

    try:
        payload = await request.json()
    except Exception:
        return {"ok": True}

    for notification in payload.get("value", []):
        # Validate clientState to reject spoofed notifications
        if notification.get("clientState") != settings.AZURE_CLIENT_SECRET[:16]:
            print("[Calendar] Ignoring notification with invalid clientState")
            continue

        event_id = (notification.get("resourceData") or {}).get("id")
        if event_id:
            background_tasks.add_task(_handle_calendar_notification, event_id)

    return {"ok": True}


@router.post("/subscribe")
async def setup_subscription():
    """Manually create or refresh the Graph calendar subscription. Call once after deployment."""
    from app.services.graph_service import create_calendar_subscription
    from app.scheduler import set_subscription_id

    if not settings.WEBHOOK_BASE_URL:
        return {"error": "WEBHOOK_BASE_URL is not set — cannot create subscription"}
    if not settings.AZURE_CLIENT_ID:
        return {"error": "Azure credentials not configured"}

    notification_url = f"{settings.WEBHOOK_BASE_URL.rstrip('/')}/calendar/webhook"
    result = await create_calendar_subscription(notification_url)
    set_subscription_id(result["id"])
    print(f"[Calendar] Subscription created: {result['id']} expires {result['expirationDateTime']}")
    return result


async def _handle_calendar_notification(event_id: str) -> None:
    """Process a Graph calendar change: accept invite, store ScheduledMeeting, schedule bot."""
    print(f"[Calendar] Processing event {event_id}")
    try:
        event = await get_event(event_id)

        if event.get("isCancelled"):
            _cancel_scheduled_meeting(event_id)
            return

        join_url = extract_join_url(event)
        subject = event.get("subject", "Teams Meeting")
        organizer_email = ((event.get("organizer") or {}).get("emailAddress") or {}).get("address")

        # Always accept the invite
        await accept_event(event_id)
        print(f"[Calendar] Accepted invite: {subject}")

        if not join_url:
            print(f"[Calendar] No Teams join URL found for '{subject}' — accepted but no bot scheduled")
            return

        start = event.get("start", {})
        start_dt = _parse_graph_datetime(start.get("dateTime", ""), start.get("timeZone", "UTC"))

        from app.repositories.organisation_repository import get_default_org_id
        org_id = get_default_org_id()

        db = SessionLocal()
        try:
            existing = db.query(ScheduledMeeting).filter_by(graph_event_id=event_id).first()
            if existing:
                existing.subject = subject
                existing.start_time = start_dt
                existing.join_url = join_url
                existing.status = "scheduled"
                db.commit()
                sched_id = existing.id
                print(f"[Calendar] Updated ScheduledMeeting id={sched_id}")
            else:
                sched = ScheduledMeeting(
                    org_id=org_id,
                    graph_event_id=event_id,
                    subject=subject,
                    start_time=start_dt,
                    join_url=join_url,
                    organizer_email=organizer_email,
                    status="scheduled",
                )
                db.add(sched)
                db.commit()
                db.refresh(sched)
                sched_id = sched.id
                print(f"[Calendar] Created ScheduledMeeting id={sched_id} for '{subject}' at {start_dt}")
        finally:
            db.close()

        schedule_bot_deployment(sched_id, org_id, join_url, subject,
                                start_dt.replace(tzinfo=timezone.utc))

    except Exception as e:
        import traceback
        print(f"[Calendar] Error handling event {event_id}: {e}")
        traceback.print_exc()


def _cancel_scheduled_meeting(event_id: str) -> None:
    """Mark a ScheduledMeeting as cancelled and remove its APScheduler job."""
    from app.scheduler import scheduler
    db = SessionLocal()
    try:
        sched = db.query(ScheduledMeeting).filter_by(graph_event_id=event_id).first()
        if sched and sched.status == "scheduled":
            sched.status = "cancelled"
            db.commit()
            job_id = f"bot_deploy_{sched.id}"
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
            print(f"[Calendar] Cancelled ScheduledMeeting id={sched.id}")
    finally:
        db.close()


def _parse_graph_datetime(dt_str: str, tz_name: str) -> datetime:
    """
    Convert a Graph API datetime string + Windows timezone name to a naive UTC datetime.
    Graph returns naive ISO strings like "2026-03-20T14:00:00.0000000" with a separate tz field.
    """
    if not dt_str:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    # Trim to microseconds precision
    if "." in dt_str:
        base, frac = dt_str.split(".", 1)
        frac = frac[:6]
        dt_str = f"{base}.{frac}"
    else:
        dt_str = dt_str[:19]

    naive_dt = datetime.fromisoformat(dt_str)
    iana_tz = _TZ_MAP.get(tz_name, "UTC")

    try:
        local_dt = naive_dt.replace(tzinfo=ZoneInfo(iana_tz))
    except ZoneInfoNotFoundError:
        local_dt = naive_dt.replace(tzinfo=timezone.utc)

    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)
