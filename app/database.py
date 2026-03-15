"""
Database connection setup.

SQLite stores everything in a single file: meetings.db
No installation needed — it's built into Python.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from pathlib import Path

# Path to the database file (created automatically if it doesn't exist)
DB_PATH = Path(__file__).parent.parent / "meetings.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

# The engine is the actual connection to the database
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# A session is like a "workspace" — you open one, do your work, then close it
SessionLocal = sessionmaker(bind=engine)


# Base class that all our table models will inherit from
class Base(DeclarativeBase):
    pass


def init_db():
    """Create all tables if they don't exist yet."""
    from app import models  # noqa: F401 — imported so Base knows about the models
    Base.metadata.create_all(bind=engine)


def get_db():
    """Open a database session, use it, then close it automatically."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
