import json
import os
import re
from datetime import datetime

from app.llm.provider_factory import get_llm_provider

OUTPUT_DIR = "outputs"


def extract_participants_from_transcript(transcript_text: str) -> list[str]:
    participants = []
    seen = set()
    known_roles = set()

    for line in transcript_text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Match "Role (Name):" format — extract the name, record the role to skip later
        paren_match = re.match(r"^([A-Za-z][A-Za-z0-9 _.-]*)\(([A-Za-z][A-Za-z0-9 _.-]{0,50})\)\s*:", line)
        if paren_match:
            role = paren_match.group(1).strip().lower()
            name = paren_match.group(2).strip()
            known_roles.add(role)
            if name and name.lower() not in seen:
                seen.add(name.lower())
                participants.append(name)
            continue

        # Match plain "Name:" format — skip if it's a known role
        match = re.match(r"^([A-Za-z][A-Za-z0-9 _.-]{0,50}):", line)
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

    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if iso_match:
        return iso_match.group(1)

    dmy_slash = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\b", text)
    if dmy_slash:
        day, month, year = dmy_slash.groups()
        return f"{year}-{month}-{day}"

    dmy_dash = re.search(r"\b(\d{2})-(\d{2})-(\d{4})\b", text)
    if dmy_dash:
        day, month, year = dmy_dash.groups()
        return f"{year}-{month}-{day}"

    return None


def build_summary_prompt(transcript_text: str) -> str:
    return f"""
You are an intelligent AI meeting assistant.

Analyze the meeting transcript below and return ONLY valid JSON.
Always respond in English regardless of the language of the transcript.
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
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "_", text)
    return text[:50].strip("_")


def save_summary_to_file(summary_data: dict) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    title = summary_data.get("meeting_title", "meeting")
    date = summary_data.get("meeting_date", datetime.now().strftime("%Y-%m-%d"))
    slug = slugify(title)
    filename = f"{slug}_{date}.json"

    # Avoid overwriting if a file with the same name already exists
    file_path = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(file_path):
        suffix = datetime.now().strftime("%H-%M-%S")
        filename = f"{slug}_{date}_{suffix}.json"
        file_path = os.path.join(OUTPUT_DIR, filename)

    summary_data["saved_to"] = file_path

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2, ensure_ascii=False)

    return file_path


def summarize_meeting(transcript_text: str):
    provider = get_llm_provider()

    detected_participants = extract_participants_from_transcript(transcript_text)
    detected_date = extract_date_from_transcript(transcript_text)

    prompt = build_summary_prompt(transcript_text)
    raw_result = provider.generate(prompt)

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

    save_summary_to_file(summary_data)

    return summary_data