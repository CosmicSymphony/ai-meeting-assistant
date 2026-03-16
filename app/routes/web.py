from pathlib import Path

from fastapi import APIRouter, Depends, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.dependencies import get_web_org_id
from app.services.summarize_service import summarize_meeting
from app.services.ask_meetings_service import ask_meetings
from app.services.ask_single_meeting_service import ask_single_meeting_question
from app.services.email_generation_service import generate_followup_email_latest, generate_followup_email
from app.services.transcription_service import transcribe_audio
from app.repositories.meeting_repository import get_recent_meetings, get_meeting_by_file, save_meeting, delete_meeting

RECORDINGS_DIR = Path("recordings")

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

MAX_AUDIO_SIZE = 25 * 1024 * 1024  # 25 MB


def render_page(
    request: Request,
    org_id: int,
    summary_result=None,
    ask_result=None,
    ask_question: str = None,
    email_result=None,
    transcript_preview=None,
    detected_language=None,
    scroll_to: str = None,
    summarize_error: str = None,
    audio_error: str = None,
    ask_error: str = None,
    email_error: str = None,
    record_error: str = None,
):
    meetings = get_recent_meetings(org_id)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "summary_result": summary_result,
            "ask_result": ask_result,
            "ask_question": ask_question,
            "email_result": email_result,
            "meetings": meetings,
            "transcript_preview": transcript_preview,
            "detected_language": detected_language,
            "scroll_to": scroll_to,
            "summarize_error": summarize_error,
            "audio_error": audio_error,
            "ask_error": ask_error,
            "email_error": email_error,
            "record_error": record_error,
        },
    )


@router.get("/", response_class=HTMLResponse)
def home(request: Request, org_id: int = Depends(get_web_org_id)):
    return render_page(request, org_id)


@router.post("/summarize", response_class=HTMLResponse)
async def summarize_transcript(request: Request, file: UploadFile = File(...), org_id: int = Depends(get_web_org_id)):
    try:
        content = await file.read()
        transcript_text = content.decode("utf-8")
        result = await summarize_meeting(transcript_text, org_id)
        return render_page(request, org_id, summary_result=result, scroll_to="card-summary-result")
    except Exception as e:
        return render_page(request, org_id, summarize_error=str(e), scroll_to="card-summarize")


@router.post("/transcribe-audio", response_class=HTMLResponse)
async def transcribe_audio_file(request: Request, file: UploadFile = File(...), org_id: int = Depends(get_web_org_id)):
    try:
        content = await file.read()

        if len(content) > MAX_AUDIO_SIZE:
            return render_page(request, org_id, audio_error="File too large. Maximum size is 25MB.", scroll_to="card-audio")

        transcript_text, _ = await transcribe_audio(content, file.filename)
        result = await summarize_meeting(transcript_text, org_id)
        return render_page(request, org_id, summary_result=result, scroll_to="card-summary-result")
    except Exception as e:
        return render_page(request, org_id, audio_error=str(e), scroll_to="card-audio")


@router.post("/transcribe-only", response_class=HTMLResponse)
async def transcribe_only(request: Request, file: UploadFile = File(...), org_id: int = Depends(get_web_org_id)):
    try:
        content = await file.read()

        if len(content) > MAX_AUDIO_SIZE:
            return render_page(request, org_id, audio_error="File too large. Maximum size is 25MB.", scroll_to="card-audio")

        transcript_text, detected_language = await transcribe_audio(content, file.filename)
        return render_page(request, org_id, transcript_preview=transcript_text, detected_language=detected_language, scroll_to="card-transcript")
    except Exception as e:
        return render_page(request, org_id, audio_error=str(e), scroll_to="card-audio")


@router.post("/ask", response_class=HTMLResponse)
async def ask_question(request: Request, question: str = Form(...), org_id: int = Depends(get_web_org_id)):
    try:
        result = await ask_meetings(question, org_id)
        return render_page(request, org_id, ask_result=result, ask_question=question, scroll_to="card-ask")
    except Exception as e:
        return render_page(request, org_id, ask_error=str(e), ask_question=question, scroll_to="card-ask")


@router.post("/generate-email", response_class=HTMLResponse)
async def generate_email(
    request: Request,
    tone: str = Form(default="professional"),
    audience: str = Form(default="team"),
    signature_name: str = Form(default=""),
    meeting_file: str = Form(default=""),
    org_id: int = Depends(get_web_org_id),
):
    try:
        meeting_file = meeting_file.strip()
        signature = signature_name.strip() or None
        if meeting_file:
            result = await generate_followup_email(
                meeting_file=meeting_file,
                org_id=org_id,
                tone=tone,
                audience=audience,
                signature=signature,
            )
        else:
            result = await generate_followup_email_latest(
                org_id=org_id,
                tone=tone,
                audience=audience,
                signature=signature,
            )
        return render_page(request, org_id, email_result=result, scroll_to="card-email")
    except Exception as e:
        return render_page(request, org_id, email_error=str(e), scroll_to="card-email")


@router.post("/record-meeting", response_class=HTMLResponse)
async def record_meeting(request: Request, audio: UploadFile = File(...), org_id: int = Depends(get_web_org_id)):
    try:
        content = await audio.read()

        if len(content) > MAX_AUDIO_SIZE:
            return render_page(request, org_id, record_error="Recording too large. Maximum size is 25MB.", scroll_to="card-record")

        # Save audio file to recordings/ folder
        RECORDINGS_DIR.mkdir(exist_ok=True)
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        audio_filename = f"recording_{timestamp}.webm"
        audio_path = RECORDINGS_DIR / audio_filename
        audio_path.write_bytes(content)

        # Transcribe then summarise (same pipeline as audio upload)
        transcript_text, _ = await transcribe_audio(content, audio_filename)
        result = await summarize_meeting(transcript_text, org_id)

        # Mark it as a browser recording in the DB
        from app.database import SessionLocal
        from app.models import Meeting
        db = SessionLocal()
        try:
            meeting = db.query(Meeting).filter_by(filename=result.get("_file"), org_id=org_id).first()
            if meeting:
                meeting.source = "browser_recording"
                meeting.audio_path = str(audio_path)
                db.commit()
        finally:
            db.close()

        return render_page(request, org_id, summary_result=result, scroll_to="card-summary-result")
    except Exception as e:
        return render_page(request, org_id, record_error=str(e), scroll_to="card-record")


@router.get("/meeting/{meeting_file}", response_class=HTMLResponse)
def meeting_detail(request: Request, meeting_file: str, org_id: int = Depends(get_web_org_id)):
    meeting = get_meeting_by_file(meeting_file, org_id)

    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    return templates.TemplateResponse(
        "meeting_detail.html",
        {
            "request": request,
            "meeting": meeting,
            "question": "",
            "answer": None,
            "meeting_error": None,
        },
    )


@router.post("/meeting/{meeting_file}/ask", response_class=HTMLResponse)
async def ask_about_single_meeting(
    request: Request,
    meeting_file: str,
    question: str = Form(...),
    org_id: int = Depends(get_web_org_id),
):
    meeting = get_meeting_by_file(meeting_file, org_id)

    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    try:
        answer = await ask_single_meeting_question(meeting, question)

        return templates.TemplateResponse(
            "meeting_detail.html",
            {
                "request": request,
                "meeting": meeting,
                "question": question,
                "answer": answer,
                "meeting_error": None,
            },
        )
    except Exception as e:
        return templates.TemplateResponse(
            "meeting_detail.html",
            {
                "request": request,
                "meeting": meeting,
                "question": question,
                "answer": None,
                "meeting_error": str(e),
            },
        )


@router.post("/meeting/{meeting_file}/delete", response_class=HTMLResponse)
async def delete_meeting_route(request: Request, meeting_file: str, org_id: int = Depends(get_web_org_id)):
    delete_meeting(meeting_file, org_id)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/web/", status_code=303)
