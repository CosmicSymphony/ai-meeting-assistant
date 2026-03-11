import json
from pathlib import Path

OUTPUTS_DIR = Path("outputs")


def _load_json_file(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _normalize_meeting(data, source_file: str = "") -> dict:
    if isinstance(data, list):
        if not data:
            raise ValueError(f"Meeting file is empty: {source_file}")
        meeting = data[0]
    elif isinstance(data, dict):
        meeting = data
    else:
        raise ValueError(f"Unsupported meeting JSON structure in file: {source_file}")

    if source_file:
        meeting["_source_file"] = source_file

    return meeting


def get_recent_meetings(limit: int = 10) -> list:
    if not OUTPUTS_DIR.exists():
        return []

    json_files = sorted(
        OUTPUTS_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    meetings = []

    for file_path in json_files[:limit]:
        try:
            data = _load_json_file(file_path)
            meeting = _normalize_meeting(data, str(file_path))
            meetings.append(meeting)
        except Exception:
            continue

    return meetings


def get_latest_meeting_file() -> str:
    if not OUTPUTS_DIR.exists():
        raise FileNotFoundError("Outputs folder not found.")

    json_files = sorted(
        OUTPUTS_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    if not json_files:
        raise FileNotFoundError("No meeting JSON files found in outputs folder.")

    return str(json_files[0])


def search_meetings_by_person(person: str, meetings: list) -> list:
    person_lower = person.lower()
    matched = []

    for meeting in meetings:
        participants = meeting.get("participants", [])
        transcript = meeting.get("transcript", "")
        meeting_summary = meeting.get("meeting_summary", "")
        action_items = meeting.get("action_items", [])

        participant_match = any(
            person_lower in str(participant).lower()
            for participant in participants
        )

        transcript_match = person_lower in transcript.lower()
        summary_match = person_lower in meeting_summary.lower()

        action_item_match = any(
            person_lower in str(item.get("owner", "")).lower()
            if isinstance(item, dict) else person_lower in str(item).lower()
            for item in action_items
        )

        if participant_match or transcript_match or summary_match or action_item_match:
            matched.append(meeting)

    return matched


def search_meetings_by_keywords(keywords: list, meetings: list) -> list:
    matched = []

    for meeting in meetings:
        searchable_parts = [
            str(meeting.get("meeting_title", "")),
            str(meeting.get("meeting_summary", "")),
            str(meeting.get("transcript", "")),
            " ".join(meeting.get("key_decisions", [])),
            " ".join(meeting.get("deadlines", [])),
            " ".join(meeting.get("risks", [])),
        ]

        action_items = meeting.get("action_items", [])
        for item in action_items:
            if isinstance(item, dict):
                searchable_parts.append(str(item.get("task", "")))
                searchable_parts.append(str(item.get("owner", "")))
                searchable_parts.append(str(item.get("deadline", "")))
            else:
                searchable_parts.append(str(item))

        searchable_text = " ".join(searchable_parts).lower()

        if any(keyword.lower() in searchable_text for keyword in keywords):
            matched.append(meeting)

    return matched


def load_meeting_from_file(meeting_file: str) -> dict:
    path = Path(meeting_file)

    if not path.exists():
        raise FileNotFoundError(f"Meeting file not found: {meeting_file}")

    data = _load_json_file(path)
    return _normalize_meeting(data, str(path))