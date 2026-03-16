from __future__ import annotations

from app.database import SessionLocal
from app.models import Organisation

# Cached default org ID so we don't hit the DB on every web request
_default_org_id: int | None = None


def get_org_by_api_key(api_key: str) -> Organisation | None:
    db = SessionLocal()
    try:
        return db.query(Organisation).filter_by(api_key=api_key).first()
    finally:
        db.close()


def get_org_by_id(org_id: int) -> Organisation | None:
    db = SessionLocal()
    try:
        return db.query(Organisation).filter_by(id=org_id).first()
    finally:
        db.close()


def get_or_create_default_org() -> Organisation:
    """
    Returns the default organisation, creating it if it doesn't exist yet.
    Called once at startup — the org_id is then cached in memory.
    """
    global _default_org_id

    db = SessionLocal()
    try:
        org = db.query(Organisation).filter_by(slug="default").first()
        if not org:
            org = Organisation(name="Default Organisation", slug="default")
            db.add(org)
            db.commit()
            db.refresh(org)
            print(f"\n[SETUP] Default organisation created.")
            print(f"[SETUP] API Key: {org.api_key}")
            print(f"[SETUP] Include this header in API requests: X-API-Key: {org.api_key}\n")
        _default_org_id = org.id
        return org
    finally:
        db.close()


def get_default_org_id() -> int:
    """Returns the cached default org ID. Call get_or_create_default_org() at startup first."""
    global _default_org_id
    if _default_org_id is None:
        get_or_create_default_org()
    return _default_org_id
