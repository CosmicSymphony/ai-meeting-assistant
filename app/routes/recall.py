from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from urllib.parse import urlparse

from app.config import settings
from app.database import SessionLocal
from app.dependencies import get_web_org_id
from app.models import BotSession, Meeting

from app.services.recall_service import (
    create_bot, get_bot, get_bot_transcript,
    format_transcript, get_bot_status_label, get_bot_recording_url,
)
from app.services.bot_processing_service import process_bot_session

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

_DONE_STATUSES = {"done", "call_ended"}
_FAILED_STATUSES = {"fatal"}


# ── Join a meeting ─────────────────────────────────────────────────────────────

@router.post("/join-meeting", response_class=HTMLResponse)
async def join_meeting(
    request: Request,
    meeting_url: str = Form(...),
    meeting_name: str = Form(default="Teams Meeting"),
    org_id: int = Depends(get_web_org_id),
):
    try:
        _ALLOWED_MEETING_DOMAINS = (
            "teams.microsoft.com",
            "zoom.us",
            "meet.google.com",
        )
        parsed = urlparse(meeting_url)
        if parsed.scheme != "https" or not any(
            parsed.netloc == d or parsed.netloc.endswith("." + d)
            for d in _ALLOWED_MEETING_DOMAINS
        ):
            return templates.TemplateResponse("bot_status.html", {
                "request": request,
                "error": "Invalid meeting URL. Please provide a Teams, Zoom, or Google Meet link.",
                "bot": None,
            })

        webhook_url = None
        if settings.WEBHOOK_BASE_URL:
            webhook_url = f"{settings.WEBHOOK_BASE_URL.rstrip('/')}/recall/webhook"

        bot_data = await create_bot(
            meeting_url=meeting_url,
            bot_name="AI Meeting Assistant",
            webhook_url=webhook_url,
        )

        bot_id = bot_data["id"]

        db = SessionLocal()
        try:
            session = BotSession(
                org_id=org_id,
                bot_id=bot_id,
                meeting_url=meeting_url,
                meeting_name=meeting_name or "Teams Meeting",
                status="created",
            )
            db.add(session)
            db.commit()
        finally:
            db.close()

        return RedirectResponse(url=f"/recall/bot/{bot_id}", status_code=303)

    except Exception as e:
        return templates.TemplateResponse("bot_status.html", {
            "request": request,
            "error": str(e),
            "bot": None,
        })


# ── Raw debug endpoint ─────────────────────────────────────────────────────────

@router.get("/bot/{bot_id}/debug")
async def bot_debug(bot_id: str):
    """Return raw Recall.ai bot data for debugging."""
    try:
        bot_data = await get_bot(bot_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot_data


# ── Bot status page (auto-refreshes until done) ────────────────────────────────

@router.get("/bot/{bot_id}", response_class=HTMLResponse)
async def bot_status_page(
    request: Request,
    bot_id: str,
    background_tasks: BackgroundTasks,
    org_id: int = Depends(get_web_org_id),
):
    db = SessionLocal()
    try:
        session = db.query(BotSession).filter_by(bot_id=bot_id, org_id=org_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Bot session not found")

        # Fetch latest status from Recall.ai
        try:
            bot_data = await get_bot(bot_id)
            recall_status = bot_data.get("status_changes", [{}])[-1].get("code", "unknown") \
                if bot_data.get("status_changes") else bot_data.get("status", "unknown")
        except Exception:
            recall_status = session.status

        # Kick off background processing — check BEFORE updating session.status
        if (recall_status in _DONE_STATUSES
                and session.meeting_id is None
                and session.status not in ("processing", "done", "failed")):
            session.status = "processing"
            db.commit()
            background_tasks.add_task(_process_bot_background, session.bot_id, session.org_id)
        elif session.status not in ("processing", "done", "failed"):
            # Sync Recall.ai status into DB (only when not in an app-managed terminal state)
            session.status = recall_status
            db.commit()

        # Use DB status as the display status (captures "processing" state)
        display_status = session.status

        # If already processed → load the saved meeting
        saved_meeting = None
        if session.meeting_id:
            saved_meeting = db.query(Meeting).filter_by(id=session.meeting_id).first()

        return templates.TemplateResponse("bot_status.html", {
            "request": request,
            "session": session,
            "status_label": get_bot_status_label(display_status),
            "recall_status": display_status,
            "saved_meeting": saved_meeting,
            "error": None,
        })
    finally:
        db.close()


# ── Recall.ai webhook ──────────────────────────────────────────────────────────

@router.post("/webhook")
async def recall_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
    except Exception:
        return {"ok": True}
    event = payload.get("event", "")
    data = payload.get("data", {})

    bot_info = data.get("bot") or data
    bot_id = bot_info.get("id") or data.get("bot_id")
    if not bot_id:
        return {"ok": True}

    status_code = ""
    if "status" in bot_info:
        status_code = bot_info["status"].get("code", "")
    elif event == "bot.status_change":
        status_code = data.get("status", {}).get("code", "")

    db = SessionLocal()
    try:
        session = db.query(BotSession).filter_by(bot_id=bot_id).first()
        if not session:
            return {"ok": True}

        should_process = (
            status_code in _DONE_STATUSES
            and session.meeting_id is None
            and session.status not in ("processing", "done", "failed")
        )

        if should_process:
            session.status = "processing"
            db.commit()
            background_tasks.add_task(_process_bot_background, bot_id, session.org_id)
        elif status_code and session.status not in ("processing", "done", "failed"):
            session.status = status_code
            db.commit()

    finally:
        db.close()

    return {"ok": True}


# ── Background processing ──────────────────────────────────────────────────────

async def _process_bot_background(bot_id: str, org_id: int):
    await process_bot_session(bot_id, org_id)
