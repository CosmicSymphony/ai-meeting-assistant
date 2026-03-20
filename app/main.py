from contextlib import asynccontextmanager
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, UploadFile, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from app.routes.web import router as web_router
from app.routes.recall import router as recall_router
from app.routes.calendar import router as calendar_router
from pydantic import BaseModel
from app.services.summarize_service import summarize_meeting
from app.services.ask_meetings_service import ask_meetings
from app.schemas.email_schemas import (
    GenerateFollowupEmailRequest,
    GenerateLatestFollowupEmailRequest,
    GenerateFollowupEmailResponse,
)
from app.services.email_generation_service import (
    generate_followup_email,
    generate_followup_email_latest,
)
from app.dependencies import get_current_org_api
from app.database import init_db, SessionLocal
from app.models import Meeting as _Meeting
from app.repositories.organisation_repository import get_or_create_default_org
from app.config import settings


async def _setup_graph_subscription() -> None:
    """
    Set up the Graph calendar subscription after the server is fully started.
    Reuses an existing subscription if one already points to our webhook URL,
    deletes stale ones, then creates a fresh one if needed.
    """
    from app.services.graph_service import (
        create_calendar_subscription, list_subscriptions, delete_subscription, renew_calendar_subscription
    )
    from app.scheduler import set_subscription_id
    notification_url = f"{settings.WEBHOOK_BASE_URL.rstrip('/')}/calendar/webhook"
    try:
        existing = await list_subscriptions()
        # Look for a subscription already pointing to our webhook
        for sub in existing:
            if sub.get("notificationUrl") == notification_url:
                # Renew and reuse it
                renewed = await renew_calendar_subscription(sub["id"])
                set_subscription_id(renewed["id"])
                print(f"[Graph] Reusing existing subscription: {renewed['id']}")
                return
            else:
                # Clean up stale subscriptions from old deployments
                await delete_subscription(sub["id"])
                print(f"[Graph] Deleted stale subscription: {sub['id']}")

        sub = await create_calendar_subscription(notification_url)
        set_subscription_id(sub["id"])
        print(f"[Graph] Calendar subscription active: {sub['id']}")
    except Exception as e:
        print(f"[Graph] Warning: could not create calendar subscription: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise DB and default org
    init_db()
    _default_org = get_or_create_default_org()

    # Assign any legacy meetings (no org_id) to the default org
    _db = SessionLocal()
    try:
        _db.query(_Meeting).filter(_Meeting.org_id == None).update({"org_id": _default_org.id})
        _db.commit()
    finally:
        _db.close()

    # Start APScheduler and reschedule any pending meetings
    from app.scheduler import scheduler, reschedule_pending_on_startup, _poll_pending_bots_job
    scheduler.start()
    reschedule_pending_on_startup()

    # Polling fallback: catch any bot sessions that missed the Recall.ai webhook
    scheduler.add_job(
        _poll_pending_bots_job,
        trigger=IntervalTrigger(minutes=1),
        id="poll_pending_bots",
        replace_existing=True,
    )

    # Schedule Graph subscription creation 15s after startup so the server is ready to validate
    if settings.WEBHOOK_BASE_URL and settings.AZURE_CLIENT_ID:
        from datetime import datetime, timedelta, timezone
        from apscheduler.triggers.date import DateTrigger
        fire_at = datetime.now(timezone.utc) + timedelta(seconds=15)
        scheduler.add_job(
            _setup_graph_subscription,
            trigger=DateTrigger(run_date=fire_at),
            id="graph_subscription_setup",
            replace_existing=True,
        )

    yield

    from app.scheduler import scheduler
    scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Server"] = "server"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    if settings.WEBHOOK_BASE_URL:  # only set HSTS when running in production (HTTPS)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(web_router, prefix="/web")
app.include_router(recall_router, prefix="/recall")
app.include_router(calendar_router, prefix="/calendar")


class MeetingQuestionRequest(BaseModel):
    question: str


@app.post("/generate_followup_email", response_model=GenerateFollowupEmailResponse)
async def generate_followup_email_endpoint(
    request: GenerateFollowupEmailRequest,
    org=Depends(get_current_org_api),
):
    try:
        result = await generate_followup_email(
            meeting_file=request.meeting_file,
            org_id=org.id,
            tone=request.tone,
            audience=request.audience,
            signature=request.signature
        )
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


@app.post("/generate_followup_email_latest", response_model=GenerateFollowupEmailResponse)
async def generate_followup_email_latest_endpoint(
    request: GenerateLatestFollowupEmailRequest,
    org=Depends(get_current_org_api),
):
    try:
        result = await generate_followup_email_latest(
            org_id=org.id,
            tone=request.tone,
            audience=request.audience,
            signature=request.signature
        )
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


@app.post("/summarize")
async def summarize(file: UploadFile, org=Depends(get_current_org_api)):
    content = await file.read()
    transcript = content.decode("utf-8")
    result = await summarize_meeting(transcript, org.id)
    return result


@app.post("/ask_meetings")
async def ask_saved_meetings(request: MeetingQuestionRequest, org=Depends(get_current_org_api)):
    return await ask_meetings(request.question, org.id)
