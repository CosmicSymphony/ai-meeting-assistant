import json
import re
from datetime import datetime

from app.llm.provider_factory import get_llm_provider
from app.repositories.meeting_repository import save_meeting

# Pre-compiled regex patterns for date extraction
_RE_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_RE_DMY_SLASH = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
_RE_DMY_DASH = re.compile(r"\b(\d{2})-(\d{2})-(\d{4})\b")

# Pre-compiled regex patterns for participant extraction
_RE_PAREN_SPEAKER = re.compile(r"^([A-Za-z][A-Za-z0-9 _.-]*)\(([A-Za-z][A-Za-z0-9 _.-]{0,50})\)\s*:")
_RE_PLAIN_SPEAKER = re.compile(r"^([A-Za-z][A-Za-z0-9 _.-]{0,50}):")

# Pre-compiled regex for slugify
_RE_SLUG_STRIP = re.compile(r"[^\w\s-]")
_RE_SLUG_SPACE = re.compile(r"[\s_]+")


def extract_participants_from_transcript(transcript_text: str) -> list[str]:
    participants = []
    seen = set()
    known_roles = set()

    for line in transcript_text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Match "Role (Name):" format — extract the name, record the role to skip later
        paren_match = _RE_PAREN_SPEAKER.match(line)
        if paren_match:
            role = paren_match.group(1).strip().lower()
            name = paren_match.group(2).strip()
            known_roles.add(role)
            if name and name.lower() not in seen:
                seen.add(name.lower())
                participants.append(name)
            continue

        # Match plain "Name:" format — skip if it's a known role
        match = _RE_PLAIN_SPEAKER.match(line)
        if match:
            name = match.group(1).strip()
            if name and name.lower() not in seen and name.lower() not in known_roles:
                seen.add(name.lower())
                participants.append(name)

    return participants


def extract_date_from_transcript(transcript_text: str) -> str | None:
    """
    Try to detect a real date from transcript text.
    Supports simple formats like:
    2026-03-12
    12/03/2026
    12-03-2026
    """
    text = transcript_text.strip()

    iso_match = _RE_ISO_DATE.search(text)
    if iso_match:
        return iso_match.group(1)

    dmy_slash = _RE_DMY_SLASH.search(text)
    if dmy_slash:
        day, month, year = dmy_slash.groups()
        return f"{year}-{month}-{day}"

    dmy_dash = _RE_DMY_DASH.search(text)
    if dmy_dash:
        day, month, year = dmy_dash.groups()
        return f"{year}-{month}-{day}"

    return None


def build_summary_prompt(transcript_text: str) -> str:
    return f"""
You are an intelligent AI meeting assistant.

Analyze the meeting transcript below and return ONLY valid JSON.
Do not include markdown.
Do not include triple backticks.
Do not include any explanation outside JSON.

Required JSON structure:
{{
  "meeting_title": "string",
  "participants": ["string"],
  "meeting_summary": "string",
  "key_decisions": ["string"],
  "action_items": [
    {{
      "task": "string",
      "owner": "string",
      "deadline": "string"
    }}
  ]
}}

Rules:
- Extract participants from the transcript if possible.
- If the meeting title is not explicitly stated, create a short sensible title.
- Keep the summary concise but useful.
- Return arrays even if there is only one item.
- Return an empty array only if truly no items are present.
- Do NOT invent dates or timestamps.

Transcript:
{transcript_text}
""".strip()


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = _RE_SLUG_STRIP.sub("", text)
    text = _RE_SLUG_SPACE.sub("_", text)
    return text[:50].strip("_")


def save_summary_to_db(summary_data: dict) -> dict:
    """Save meeting summary to the database and return the dict with _file set."""
    meeting = save_meeting(summary_data)
    summary_data["_file"] = meeting.filename
    summary_data["id"] = meeting.id
    return summary_data


async def summarize_meeting(transcript_text: str):
    provider = get_llm_provider()

    detected_participants = extract_participants_from_transcript(transcript_text)
    detected_date = extract_date_from_transcript(transcript_text)

    prompt = build_summary_prompt(transcript_text)
    raw_result = await provider.generate(prompt)

    if isinstance(raw_result, str):
        summary_data = json.loads(raw_result)
    else:
        summary_data = raw_result

    summary_data["transcript"] = transcript_text

    # Prefer deterministic participant extraction if found
    if detected_participants:
        summary_data["participants"] = detected_participants
    elif not summary_data.get("participants"):
        summary_data["participants"] = []

    # Date should not be invented by AI
    now = datetime.now()
    if detected_date:
        summary_data["meeting_date"] = detected_date
    else:
        summary_data["meeting_date"] = now.strftime("%Y-%m-%d")

    summary_data["meeting_timestamp"] = now.strftime("%Y-%m-%d %H:%M:%S")

    save_summary_to_db(summary_data)

    return summary_data