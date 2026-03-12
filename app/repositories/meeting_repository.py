import os
import json
from typing import List, Dict, Any, Optional

OUTPUT_DIR = "outputs"


def _list_meeting_files() -> List[str]:
    if not os.path.exists(OUTPUT_DIR):
        return []

    files = [
        f for f in os.listdir(OUTPUT_DIR)
        if f.startswith("meeting_summary") and f.endswith(".json")
    ]
    files.sort(reverse=True)
    return files


def _build_file_path(filename: str) -> str:
    return os.path.join(OUTPUT_DIR, filename)


def _load_json_file(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "saved_to" not in data:
            data["saved_to"] = path

        if "source_file" not in data:
            data["source_file"] = os.path.basename(path)

        return data
    except Exception:
        return None


def load_meeting_from_file(filename: str) -> Optional[Dict[str, Any]]:
    """
    Public function expected by older services.
    Accepts a filename like 'meeting_summary_....json'
    """
    path = _build_file_path(filename)
    return _load_json_file(path)


def get_all_meetings() -> List[Dict[str, Any]]:
    meetings = []

    for filename in _list_meeting_files():
        data = load_meeting_from_file(filename)
        if data:
            meetings.append(data)

    return meetings


def get_recent_meetings(limit: int = 10) -> List[Dict[str, Any]]:
    meetings = []

    for filename in _list_meeting_files()[:limit]:
        data = load_meeting_from_file(filename)
        if not data:
            continue

        meetings.append({
            "title": data.get("meeting_title", "Untitled Meeting"),
            "date": data.get("meeting_date", ""),
            "timestamp": data.get("meeting_timestamp", ""),
            "file": filename,
            "saved_to": data.get("saved_to", ""),
        })

    return meetings


def get_latest_meeting() -> Optional[Dict[str, Any]]:
    files = _list_meeting_files()
    if not files:
        return None

    return load_meeting_from_file(files[0])


def get_latest_meeting_file() -> Optional[str]:
    """
    Backward-compatible helper in case older services want the newest filename.
    """
    files = _list_meeting_files()
    if not files:
        return None
    return files[0]


def search_meetings_by_person(person_name: str) -> List[Dict[str, Any]]:
    results = []
    person_name_lower = person_name.strip().lower()

    for meeting in get_all_meetings():
        participants = meeting.get("participants", [])
        participant_names = [str(p).strip().lower() for p in participants]

        action_items = meeting.get("action_items", [])
        action_item_owners = [
            str(item.get("owner", "")).strip().lower()
            for item in action_items
            if isinstance(item, dict)
        ]

        if (
            person_name_lower in participant_names
            or person_name_lower in action_item_owners
        ):
            results.append(meeting)

    return results


def search_meetings_by_keyword(keyword: str) -> List[Dict[str, Any]]:
    results = []
    keyword_lower = keyword.strip().lower()

    for meeting in get_all_meetings():
        searchable_parts = [
            meeting.get("meeting_title", ""),
            meeting.get("meeting_summary", ""),
            " ".join(meeting.get("key_decisions", [])),
            " ".join(meeting.get("risks", [])),
            " ".join(
                [
                    item.get("task", "")
                    for item in meeting.get("action_items", [])
                    if isinstance(item, dict)
                ]
            ),
            " ".join(meeting.get("participants", [])),
        ]

        full_text = " ".join([str(part) for part in searchable_parts]).lower()

        if keyword_lower in full_text:
            results.append(meeting)

    return results


def search_meetings_by_keywords(keyword: str) -> List[Dict[str, Any]]:
    """
    Backward-compatible alias for older imports using plural naming.
    """
    return search_meetings_by_keyword(keyword)


def search_meetings(query: str) -> List[Dict[str, Any]]:
    results = []
    query_lower = query.strip().lower()

    for meeting in get_all_meetings():
        action_items = meeting.get("action_items", [])

        searchable_parts = [
            meeting.get("meeting_title", ""),
            meeting.get("meeting_summary", ""),
            " ".join(meeting.get("key_decisions", [])),
            " ".join(meeting.get("risks", [])),
            " ".join(meeting.get("participants", [])),
            " ".join(
                [
                    item.get("task", "")
                    for item in action_items
                    if isinstance(item, dict)
                ]
            ),
            " ".join(
                [
                    item.get("owner", "")
                    for item in action_items
                    if isinstance(item, dict)
                ]
            ),
            " ".join(
                [
                    item.get("deadline", "")
                    for item in action_items
                    if isinstance(item, dict)
                ]
            ),
        ]

        full_text = " ".join([str(part) for part in searchable_parts]).lower()

        if query_lower in full_text:
            results.append(meeting)

    return results