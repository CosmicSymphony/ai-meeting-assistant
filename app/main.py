from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.staticfiles import StaticFiles
from app.routes.web import router as web_router
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


from app.database import init_db
init_db()

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(web_router, prefix="/web")

class MeetingQuestionRequest(BaseModel):
    question: str


@app.post("/generate_followup_email", response_model=GenerateFollowupEmailResponse)
async def generate_followup_email_endpoint(request: GenerateFollowupEmailRequest):
    try:
        result = await generate_followup_email(
            meeting_file=request.meeting_file,
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
async def generate_followup_email_latest_endpoint(request: GenerateLatestFollowupEmailRequest):
    try:
        result = await generate_followup_email_latest(
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
async def summarize(file: UploadFile):
    content = await file.read()
    transcript = content.decode("utf-8")
    result = await summarize_meeting(transcript)
    return result


@app.post("/ask_meetings")
async def ask_saved_meetings(request: MeetingQuestionRequest):
    return await ask_meetings(request.question)
