from __future__ import annotations

import time
from datetime import date
from typing import Any, Dict, List, Optional

from app.database import SessionLocal
from app.models import Meeting


# ── Simple in-memory cache (avoids hitting the DB on every page render) ───────
_meetings_cache: List[Dict[str, Any]] | None = None
_cache_timestamp: float = 0.0
_CACHE_TTL: float = 30.0  # seconds


def _invalidate_cache() -> None:
    global _meetings_cache, _cache_timestamp
    _meetings_cache = None
    _cache_timestamp = 0.0


# ── Read one meeting ───────────────────────────────────────────────────────────

def load_meeting_from_file(filename: str) -> Optional[Dict[str, Any]]:
    """Load a single meeting by its filename."""
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter_by(filename=filename).first()
        return meeting.to_dict() if meeting else None
    finally:
        db.close()


def get_meeting_by_file(filename: str) -> Optional[Dict[str, Any]]:
    return load_meeting_from_file(filename)


def get_meeting_by_id(meeting_id: int) -> Optional[Dict[str, Any]]:
    """Load a single meeting by its database ID."""
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter_by(id=meeting_id).first()
        return meeting.to_dict() if meeting else None
    finally:
        db.close()


# ── Read all meetings ──────────────────────────────────────────────────────────

def get_all_meetings() -> List[Dict[str, Any]]:
    """Return all meetings, newest first. Results are cached for 30 seconds."""
    global _meetings_cache, _cache_timestamp

    now = time.monotonic()
    if _meetings_cache is not None and (now - _cache_timestamp) < _CACHE_TTL:
        return _meetings_cache

    db = SessionLocal()
    try:
        rows = (
            db.query(Meeting)
            .order_by(Meeting.created_at.desc())
            .all()
        )
        _meetings_cache = [m.to_dict() for m in rows]
        _cache_timestamp = now
        return _meetings_cache
    finally:
        db.close()


def get_recent_meetings(limit: int = 5) -> List[Dict[str, Any]]:
    return get_all_meetings()[:limit]


def get_latest_meeting_file() -> str:
    """Return the filename of the most recently saved meeting."""
    meetings = get_all_meetings()
    if not meetings:
        raise FileNotFoundError("No meetings found in database.")
    return meetings[0]["_file"]


# ── Save a meeting ─────────────────────────────────────────────────────────────

def save_meeting(data: dict) -> Meeting:
    """
    Insert a new meeting row from a summary dict.
    Returns the saved Meeting object (with its new id and filename).
    """
    from datetime import datetime
    import re

    def slugify(text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"[\s_]+", "_", text)
        return text[:50].strip("_")

    title = data.get("meeting_title", "meeting")
    meeting_date = data.get("meeting_date", datetime.now().strftime("%Y-%m-%d"))
    slug = slugify(title)
    filename = f"{slug}_{meeting_date}.json"

    db = SessionLocal()
    try:
        # Avoid duplicate filenames
        if db.query(Meeting).filter_by(filename=filename).first():
            suffix = datetime.now().strftime("%H-%M-%S")
            filename = f"{slug}_{meeting_date}_{suffix}.json"

        meeting = Meeting()
        meeting.title           = title
        meeting.date            = meeting_date
        meeting.timestamp       = data.get("meeting_timestamp")
        meeting.transcript      = data.get("transcript")
        meeting.meeting_summary = data.get("meeting_summary")
        meeting.participants    = data.get("participants", [])
        meeting.key_decisions   = data.get("key_decisions", [])
        meeting.action_items    = data.get("action_items", [])
        meeting.filename        = filename
        meeting.source          = data.get("source", "upload")
        meeting.status          = "ready"

        db.add(meeting)
        db.commit()
        db.refresh(meeting)

        _invalidate_cache()
        return meeting
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_meeting(filename: str) -> bool:
    """Delete a meeting by filename. Returns True if deleted, False if not found."""
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter_by(filename=filename).first()
        if not meeting:
            return False
        db.delete(meeting)
        db.commit()
        _invalidate_cache()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Search helpers ─────────────────────────────────────────────────────────────

def _build_search_text(meeting: Dict[str, Any]) -> str:
    """Build a normalised searchable string for a meeting dict."""
    if "_search_text" in meeting:
        return meeting["_search_text"]

    action_items = meeting.get("action_items", []) or []
    action_text = " ".join(
        f"{item.get('task', '')} {item.get('owner', '')} {item.get('deadline', '')}"
        if isinstance(item, dict)
        else str(item)
        for item in action_items
    )

    text = " ".join([
        str(meeting.get("meeting_title", "")),
        str(meeting.get("meeting_summary", "")),
        " ".join(str(x) for x in meeting.get("key_decisions", [])),
        action_text,
        str(meeting.get("transcript", "")),
    ]).lower()

    meeting["_search_text"] = text
    return text


def search_meetings_by_person(
    person_name: str,
    meetings: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if not person_name:
        return []
    if meetings is None:
        meetings = get_all_meetings()

    target = person_name.strip().lower()
    matches = []
    for meeting in meetings:
        participants = meeting.get("participants", []) or []
        if any(target in str(p).lower() for p in participants):
            matches.append(meeting)
            continue
        if target in _build_search_text(meeting):
            matches.append(meeting)
    return matches


def search_meetings_by_date(
    target_date: date,
    meetings: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if meetings is None:
        meetings = get_all_meetings()
    target_str = target_date.strftime("%Y-%m-%d")
    return [m for m in meetings if m.get("meeting_date", "") == target_str]


def search_meetings_by_keywords(
    keywords: List[str],
    meetings: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if not keywords:
        return []
    if meetings is None:
        meetings = get_all_meetings()

    normalized = [kw.strip().lower() for kw in keywords if kw and kw.strip()]
    return [
        m for m in meetings
        if any(kw in _build_search_text(m) for kw in normalized)
    ]
