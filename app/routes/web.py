import json

from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.summarize_service import summarize_meeting
from app.services.ask_meetings_service import ask_meetings
from app.services.ask_single_meeting_service import ask_single_meeting_question
from app.services.email_generation_service import generate_followup_email_latest
from app.repositories.meeting_repository import get_recent_meetings, get_meeting_by_file

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def render_page(
    request: Request,
    summary_result=None,
    ask_result=None,
    email_result=None,
    error=None,
):
    meetings = get_recent_meetings()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "summary_result": summary_result,
            "ask_result": ask_result,
            "email_result": email_result,
            "error": error,
            "meetings": meetings,
        },
    )


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    return render_page(request)


@router.post("/summarize", response_class=HTMLResponse)
async def summarize_transcript(request: Request, file: UploadFile = File(...)):
    try:
        content = await file.read()
        transcript_text = content.decode("utf-8")
        result = summarize_meeting(transcript_text)

        if isinstance(result, str):
            result = json.loads(result)

        return render_page(request, summary_result=result)
    except Exception as e:
        return render_page(request, error=str(e))


@router.post("/ask", response_class=HTMLResponse)
async def ask_question(request: Request, question: str = Form(...)):
    try:
        result = ask_meetings(question)
        return render_page(request, ask_result=result)
    except Exception as e:
        return render_page(request, error=str(e))


@router.post("/generate-latest-email", response_class=HTMLResponse)
async def generate_latest_email(
    request: Request,
    signature_name: str = Form(default=""),
):
    try:
        result = generate_followup_email_latest()

        if signature_name.strip():
            result = f"{result}\n\nBest regards,\n{signature_name}"

        return render_page(request, email_result=result)
    except Exception as e:
        return render_page(request, error=str(e))


@router.get("/meeting/{meeting_file}", response_class=HTMLResponse)
def meeting_detail(request: Request, meeting_file: str):
    meeting = get_meeting_by_file(meeting_file)

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
):
    meeting = get_meeting_by_file(meeting_file)

    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    try:
        answer = ask_single_meeting_question(meeting, question)

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