from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import SessionLocal
from app.dependencies import get_web_org_id
from app.models import BotSession, Meeting
from app.services.recall_service import (
    create_bot, get_bot, get_bot_transcript,
    format_transcript, get_bot_status_label,
)
from app.services.summarize_service import summarize_meeting

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


# ── Bot status page (auto-refreshes until done) ────────────────────────────────

@router.get("/bot/{bot_id}", response_class=HTMLResponse)
async def bot_status_page(request: Request, bot_id: str, org_id: int = Depends(get_web_org_id)):
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

            session.status = recall_status
            db.commit()
        except Exception:
            recall_status = session.status

        # If done and not yet processed → process now
        meeting_data = None
        if recall_status in _DONE_STATUSES and session.meeting_id is None:
            meeting_data = await _process_bot(session, org_id, db)

        # If already processed → load the saved meeting
        saved_meeting = None
        if session.meeting_id:
            saved_meeting = db.query(Meeting).filter_by(id=session.meeting_id).first()

        return templates.TemplateResponse("bot_status.html", {
            "request": request,
            "session": session,
            "status_label": get_bot_status_label(recall_status),
            "recall_status": recall_status,
            "saved_meeting": saved_meeting,
            "error": None,
        })
    finally:
        db.close()


# ── Recall.ai webhook ──────────────────────────────────────────────────────────

@router.post("/webhook")
async def recall_webhook(request: Request):
    """
    Recall.ai calls this endpoint when bot status changes.
    Processes the transcript when the call ends.
    """
    payload = await request.json()
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

        if status_code:
            session.status = status_code
            db.commit()

        if status_code in _DONE_STATUSES and session.meeting_id is None:
            await _process_bot(session, session.org_id, db)

    finally:
        db.close()

    return {"ok": True}


# ── Shared processing helper ───────────────────────────────────────────────────

async def _process_bot(session: BotSession, org_id: int, db) -> dict | None:
    """Fetch transcript from Recall.ai, summarize, and save as a Meeting."""
    try:
        raw = await get_bot_transcript(session.bot_id)
        transcript_text = format_transcript(raw)

        if not transcript_text.strip():
            session.status = "failed"
            db.commit()
            return None

        summary = await summarize_meeting(transcript_text, org_id)

        # Link the bot session to the saved meeting
        meeting = db.query(Meeting).filter_by(filename=summary.get("_file"), org_id=org_id).first()
        if meeting:
            meeting.source = "teams"
            session.meeting_id = meeting.id
            db.commit()

        return summary
    except Exception as e:
        session.status = "failed"
        db.commit()
        raise e
