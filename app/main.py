from fastapi import FastAPI, UploadFile, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from app.routes.web import router as web_router
from app.routes.recall import router as recall_router
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
from app.database import init_db
from app.repositories.organisation_repository import get_or_create_default_org

init_db()
_default_org = get_or_create_default_org()

# Assign any legacy meetings (no org_id) to the default org
from app.database import SessionLocal
from app.models import Meeting as _Meeting
_db = SessionLocal()
try:
    _db.query(_Meeting).filter(_Meeting.org_id == None).update({"org_id": _default_org.id})
    _db.commit()
finally:
    _db.close()

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(web_router, prefix="/web")
app.include_router(recall_router, prefix="/recall")


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
