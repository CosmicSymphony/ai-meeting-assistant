from pydantic import BaseModel
from typing import Optional


class GenerateFollowupEmailRequest(BaseModel):
    meeting_file: str
    tone: Optional[str] = "professional"
    audience: Optional[str] = "team"
    signature: Optional[str] = None


class GenerateLatestFollowupEmailRequest(BaseModel):
    tone: Optional[str] = "professional"
    audience: Optional[str] = "team"
    signature: Optional[str] = None


class GenerateFollowupEmailResponse(BaseModel):
    subject: str
    email_body: str