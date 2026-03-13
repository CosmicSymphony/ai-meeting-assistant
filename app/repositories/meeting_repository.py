from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

OUTPUTS_DIR = Path("outputs")


def load_meeting_from_file(filename: str) -> Optional[Dict[str, Any]]:
    """
    Load one saved meeting JSON file from the outputs folder.
    """
    file_path = OUTPUTS_DIR / filename

    if not file_path.exists() or not file_path.is_file():
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            data["_file"] = filename
            data["_source_file"] = filename

        return data

    except Exception:
        return None


def get_meeting_by_file(filename: str) -> Optional[Dict[str, Any]]:
    """
    Public helper for loading one meeting by filename.
    """
    return load_meeting_from_file(filename)


def get_all_meetings() -> List[Dict[str, Any]]:
    """
    Load all meeting JSON files from outputs folder.
    Sorted by newest modified first.
    """
    if not OUTPUTS_DIR.exists():
        return []

    meetings: List[Dict[str, Any]] = []

    json_files = sorted(
        OUTPUTS_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    for file_path in json_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                data["_file"] = file_path.name
                data["_source_file"] = file_path.name
                meetings.append(data)

        except Exception:
            continue

    return meetings


def get_recent_meetings(limit: int = 5) -> List[Dict[str, Any]]:
    """
    Return the most recent meetings.

    Keeps the FULL meeting objects because other services depend on fields like:
    - meeting_title
    - participants
    - meeting_summary
    - transcript
    """
    meetings = get_all_meetings()
    return meetings[:limit]


def get_latest_meeting_file() -> str:
    """
    Return the newest meeting filename.
    """
    meetings = get_all_meetings()

    if not meetings:
        raise FileNotFoundError("No meeting files found.")

    return meetings[0]["_file"]


def search_meetings_by_person(
    person_name: str,
    meetings: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """
    Search meetings by participant name.
    """
    if not person_name:
        return []

    if meetings is None:
        meetings = get_all_meetings()

    target = person_name.strip().lower()

    matches: List[Dict[str, Any]] = []

    for meeting in meetings:

        participants = meeting.get("participants", []) or []

        if any(target in str(p).lower() for p in participants):
            matches.append(meeting)
            continue

        searchable_text = " ".join([
            str(meeting.get("meeting_title", "")),
            str(meeting.get("meeting_summary", "")),
            str(meeting.get("transcript", "")),
        ]).lower()

        if target in searchable_text:
            matches.append(meeting)

    return matches


def search_meetings_by_keywords(
    keywords: List[str],
    meetings: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """
    Search meetings by keywords across title, summary,
    decisions, risks, action items and transcript.
    """
    if not keywords:
        return []

    if meetings is None:
        meetings = get_all_meetings()

    normalized_keywords = [
        kw.strip().lower()
        for kw in keywords
        if kw and kw.strip()
    ]

    matches: List[Dict[str, Any]] = []

    for meeting in meetings:

        action_items = meeting.get("action_items", []) or []

        action_items_text = " ".join(
            f"{item.get('task','')} {item.get('owner','')} {item.get('deadline','')}"
            if isinstance(item, dict)
            else str(item)
            for item in action_items
        )

        searchable_text = " ".join([
            str(meeting.get("meeting_title", "")),
            str(meeting.get("meeting_summary", "")),
            " ".join(str(x) for x in meeting.get("key_decisions", [])),
            " ".join(str(x) for x in meeting.get("risks", [])),
            action_items_text,
            str(meeting.get("transcript", "")),
        ]).lower()

        if any(keyword in searchable_text for keyword in normalized_keywords):
            matches.append(meeting)

    return matches