from app.llm.provider_factory import get_llm_provider
from app.repositories.meeting_repository import (
    load_meeting_from_file,
    get_latest_meeting_file,
)


def build_followup_email_prompt(meeting_data: dict, tone: str, audience: str, signature: str | None) -> str:
    meeting_title = meeting_data.get("meeting_title", "Meeting")
    meeting_date = meeting_data.get("meeting_date", "")
    participants = meeting_data.get("participants", [])
    meeting_summary = meeting_data.get("meeting_summary", "")
    key_decisions = meeting_data.get("key_decisions", [])
    action_items = meeting_data.get("action_items", [])

    participants_text = ", ".join(participants) if participants else "Not specified"

    if key_decisions:
        key_decisions_text = "\n".join([f"- {item}" for item in key_decisions])
    else:
        key_decisions_text = "- No key decisions recorded."

    if action_items:
        formatted_action_items = []
        for item in action_items:
            if isinstance(item, dict):
                task = item.get("task", "No task provided")
                owner = item.get("owner", "Not assigned")
                deadline = item.get("deadline", "No deadline")
                formatted_action_items.append(f"- {task} (Owner: {owner}, Deadline: {deadline})")
            else:
                formatted_action_items.append(f"- {str(item)}")
        action_items_text = "\n".join(formatted_action_items)
    else:
        action_items_text = "- No action items recorded."

    signature_instruction = (
        f'Use this exact email signature at the end of the email:\n{signature}'
        if signature
        else "End the email with a natural professional closing, but do not invent a personal name or job title."
    )

    return f"""
You are an intelligent AI meeting assistant.

Write a clear follow-up email based only on the meeting details below.

Rules:
- Be factual and do not invent details
- Keep it professional and natural
- Include the main summary
- Include key decisions if useful
- Include action items clearly
- {signature_instruction}
- Return the output in this exact format:

SUBJECT: <email subject>
BODY:
<email body>

Meeting title: {meeting_title}
Meeting date: {meeting_date}
Participants: {participants_text}
Audience: {audience}
Tone: {tone}

Meeting summary:
{meeting_summary}

Key decisions:
{key_decisions_text}

Action items:
{action_items_text}
""".strip()


def parse_email_response(text: str, meeting_title: str) -> dict:
    subject = f"Follow-Up: {meeting_title}"
    body = text.strip()

    if "SUBJECT:" in text and "BODY:" in text:
        after_subject = text.split("SUBJECT:", 1)[1]
        parts = after_subject.split("BODY:", 1)
        if len(parts) == 2:
            subject_part = parts[0].strip()
            body_part = parts[1].strip()
            if subject_part:
                subject = subject_part
            if body_part:
                body = body_part

    return {"subject": subject, "email_body": body}


async def generate_followup_email(
    meeting_file: str,
    tone: str = "professional",
    audience: str = "team",
    signature: str | None = None
) -> dict:
    meeting_data = load_meeting_from_file(meeting_file)

    prompt = build_followup_email_prompt(
        meeting_data=meeting_data,
        tone=tone,
        audience=audience,
        signature=signature
    )

    provider = get_llm_provider()
    llm_response = await provider.generate(prompt)

    return parse_email_response(
        text=llm_response,
        meeting_title=meeting_data.get("meeting_title", "Meeting")
    )


async def generate_followup_email_latest(
    tone: str = "professional",
    audience: str = "team",
    signature: str | None = None
) -> dict:
    latest_meeting_file = get_latest_meeting_file()

    return await generate_followup_email(
        meeting_file=latest_meeting_file,
        tone=tone,
        audience=audience,
        signature=signature
    )
