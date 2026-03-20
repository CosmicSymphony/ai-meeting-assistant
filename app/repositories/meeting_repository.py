from __future__ import annotations

import re
import time
from datetime import date
from typing import Any, Dict, List, Optional

from app.database import SessionLocal
from app.models import Meeting

_RE_SLUG_STRIP = re.compile(r"[^\w\s-]")
_RE_SLUG_SPACE = re.compile(r"[\s_]+")


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = _RE_SLUG_STRIP.sub("", text)
    text = _RE_SLUG_SPACE.sub("_", text)
    return text[:50].strip("_")


# ── Per-tenant in-memory cache ─────────────────────────────────────────────────
_meetings_cache: Dict[int, List[Dict[str, Any]]] = {}
_cache_timestamps: Dict[int, float] = {}
_CACHE_TTL: float = 30.0  # seconds


def _invalidate_cache(org_id: int) -> None:
    _meetings_cache.pop(org_id, None)
    _cache_timestamps.pop(org_id, None)


# ── Read one meeting ───────────────────────────────────────────────────────────

def load_meeting_from_file(filename: str, org_id: int) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter_by(filename=filename, org_id=org_id).first()
        return meeting.to_dict() if meeting else None
    finally:
        db.close()


def get_meeting_by_file(filename: str, org_id: int | None = None) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        query = db.query(Meeting).filter_by(filename=filename)
        if org_id is not None:
            query = query.filter_by(org_id=org_id)
        meeting = query.first()
        return meeting.to_dict() if meeting else None
    finally:
        db.close()


def get_meeting_by_id(meeting_id: int, org_id: int) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter_by(id=meeting_id, org_id=org_id).first()
        return meeting.to_dict() if meeting else None
    finally:
        db.close()


# ── Read all meetings ──────────────────────────────────────────────────────────

def get_all_meetings(org_id: int) -> List[Dict[str, Any]]:
    """Return all meetings for an org, newest first. Results are cached per tenant."""
    now = time.monotonic()
    cached = _meetings_cache.get(org_id)
    ts = _cache_timestamps.get(org_id, 0.0)

    if cached is not None and (now - ts) < _CACHE_TTL:
        return cached

    db = SessionLocal()
    try:
        rows = (
            db.query(Meeting)
            .filter_by(org_id=org_id)
            .order_by(Meeting.created_at.desc())
            .all()
        )
        result = [m.to_dict() for m in rows]
        _meetings_cache[org_id] = result
        _cache_timestamps[org_id] = now
        return result
    finally:
        db.close()


def get_recent_meetings(org_id: int, limit: int = 5) -> List[Dict[str, Any]]:
    return get_all_meetings(org_id)[:limit]


def get_latest_meeting_file(org_id: int) -> str:
    meetings = get_all_meetings(org_id)
    if not meetings:
        raise FileNotFoundError("No meetings found.")
    return meetings[0]["_file"]


# ── Save a meeting ─────────────────────────────────────────────────────────────

def save_meeting(data: dict, org_id: int) -> Meeting:
    """Insert a new meeting row. Returns the saved Meeting object."""
    from datetime import datetime

    title = data.get("meeting_title", "meeting")
    meeting_date = data.get("meeting_date", datetime.now().strftime("%Y-%m-%d"))
    slug = slugify(title)
    filename = f"{slug}_{meeting_date}.json"

    db = SessionLocal()
    try:
        # Avoid duplicate filenames within the same org
        if db.query(Meeting).filter_by(filename=filename, org_id=org_id).first():
            suffix = datetime.now().strftime("%H-%M-%S")
            filename = f"{slug}_{meeting_date}_{suffix}.json"

        meeting = Meeting()
        meeting.org_id          = org_id
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

        _invalidate_cache(org_id)
        return meeting
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_meeting(filename: str, org_id: int) -> bool:
    """Delete a meeting by filename within an org. Returns True if deleted."""
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter_by(filename=filename, org_id=org_id).first()
        if not meeting:
            return False
        db.delete(meeting)
        db.commit()
        _invalidate_cache(org_id)
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Search helpers ─────────────────────────────────────────────────────────────

def _build_search_text(meeting: Dict[str, Any]) -> str:
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
    org_id: int | None = None,
) -> List[Dict[str, Any]]:
    if not person_name:
        return []
    if meetings is None:
        meetings = get_all_meetings(org_id)

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
    org_id: int | None = None,
) -> List[Dict[str, Any]]:
    if meetings is None:
        meetings = get_all_meetings(org_id)
    target_str = target_date.strftime("%Y-%m-%d")
    return [m for m in meetings if m.get("meeting_date", "") == target_str]


def search_meetings_by_keywords(
    keywords: List[str],
    meetings: Optional[List[Dict[str, Any]]] = None,
    org_id: int | None = None,
) -> List[Dict[str, Any]]:
    if not keywords:
        return []
    if meetings is None:
        meetings = get_all_meetings(org_id)

    normalized = [kw.strip().lower() for kw in keywords if kw and kw.strip()]
    return [
        m for m in meetings
        if any(kw in _build_search_text(m) for kw in normalized)
    ]
