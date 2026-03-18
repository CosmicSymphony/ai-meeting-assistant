from contextlib import asynccontextmanager
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
    from app.scheduler import scheduler, reschedule_pending_on_startup
    scheduler.start()
    reschedule_pending_on_startup()

    # Set up Microsoft Graph calendar subscription (only if Azure creds are configured)
    if settings.WEBHOOK_BASE_URL and settings.AZURE_CLIENT_ID:
        from app.services.graph_service import create_calendar_subscription
        from app.scheduler import set_subscription_id
        notification_url = f"{settings.WEBHOOK_BASE_URL.rstrip('/')}/calendar/webhook"
        try:
            sub = await create_calendar_subscription(notification_url)
            set_subscription_id(sub["id"])
            print(f"[Graph] Calendar subscription active: {sub['id']}")
        except Exception as e:
            print(f"[Graph] Warning: could not create calendar subscription: {e}")

    yield

    from app.scheduler import scheduler
    scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)

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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/summarize")
async def summarize(file: UploadFile, org=Depends(get_current_org_api)):
    content = await file.read()
    transcript = content.decode("utf-8")
    result = await summarize_meeting(transcript, org.id)
    return result


@app.post("/ask_meetings")
async def ask_saved_meetings(request: MeetingQuestionRequest, org=Depends(get_current_org_api)):
    return await ask_meetings(request.question, org.id)
