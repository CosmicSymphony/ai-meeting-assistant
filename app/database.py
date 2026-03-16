"""
Database connection setup.

Supports both SQLite (local dev) and PostgreSQL (production).
Set DATABASE_URL in .env to switch between them.
"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import settings

DATABASE_URL = settings.DATABASE_URL

# SQLite requires check_same_thread=False; PostgreSQL does not
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# The engine is the actual connection to the database
engine = create_engine(DATABASE_URL, connect_args=_connect_args)

# A session is like a "workspace" — you open one, do your work, then close it
SessionLocal = sessionmaker(bind=engine)


# Base class that all our table models will inherit from
class Base(DeclarativeBase):
    pass


def init_db():
    """Create all tables if they don't exist yet, and run any pending column migrations."""
    from app import models  # noqa: F401 — imported so Base knows about the models
    Base.metadata.create_all(bind=engine)
    _migrate()


def _migrate():
    """Add new columns to existing tables for SQLite (which doesn't support ALTER TABLE ADD COLUMN easily)."""
    if not DATABASE_URL.startswith("sqlite"):
        return  # PostgreSQL handles this via proper migrations (Alembic)

    with engine.connect() as conn:
        # Check if org_id column exists on meetings table
        result = conn.execute(text("PRAGMA table_info(meetings)"))
        columns = {row[1] for row in result}
        if "org_id" not in columns:
            conn.execute(text("ALTER TABLE meetings ADD COLUMN org_id INTEGER REFERENCES organisations(id)"))
            conn.commit()
            print("[MIGRATE] Added org_id column to meetings table.")

        # bot_sessions table is created by create_all above; no column migrations needed yet


def get_db():
    """Open a database session, use it, then close it automatically."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
