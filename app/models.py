"""
Database table definitions.

Each class here = one table in the database.
Each attribute = one column (like a spreadsheet column).
"""

import json
import secrets
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class Organisation(Base):
    """Represents a company/tenant. All meetings belong to an organisation."""
    __tablename__ = "organisations"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    name       = Column(String, nullable=False)
    slug       = Column(String, unique=True, nullable=False)
    api_key    = Column(String, unique=True, nullable=False, default=lambda: secrets.token_hex(32))
    created_at = Column(DateTime, default=datetime.utcnow)

    meetings = relationship("Meeting", back_populates="organisation")


class Meeting(Base):
    __tablename__ = "meetings"

    # Every row gets a unique number automatically
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Which organisation (tenant) this meeting belongs to
    org_id = Column(Integer, ForeignKey("organisations.id"), nullable=True, index=True)
    organisation = relationship("Organisation", back_populates="meetings")

    # Basic info
    title        = Column(String, nullable=True)
    date         = Column(String, nullable=True)   # e.g. "2026-03-14"
    timestamp    = Column(String, nullable=True)   # e.g. "2026-03-14 13:46:25"
    filename     = Column(String, nullable=True)   # original .json filename for backwards compat

    # Where did this meeting come from?
    # Values: "upload", "browser_recording", "zoom", "teams"
    source = Column(String, default="upload")

    # Processing state
    # Values: "ready", "processing", "failed"
    status = Column(String, default="ready")

    # The full transcript text
    transcript = Column(Text, nullable=True)

    # AI-generated content (stored as JSON strings internally)
    _meeting_summary = Column("meeting_summary", Text, nullable=True)
    _participants    = Column("participants",    Text, nullable=True)
    _key_decisions   = Column("key_decisions",  Text, nullable=True)
    _action_items    = Column("action_items",   Text, nullable=True)

    # Path to the recorded audio file (if captured via browser recording)
    audio_path = Column(String, nullable=True)

    # When was this row created in the database?
    created_at = Column(DateTime, default=datetime.utcnow)

    # ── Helpers to read/write lists and dicts as JSON ─────────
    # SQLite stores everything as text, so we convert to/from JSON automatically

    @property
    def meeting_summary(self):
        return self._meeting_summary

    @meeting_summary.setter
    def meeting_summary(self, value):
        self._meeting_summary = value

    @property
    def participants(self):
        return json.loads(self._participants) if self._participants else []

    @participants.setter
    def participants(self, value):
        self._participants = json.dumps(value) if value is not None else None

    @property
    def key_decisions(self):
        return json.loads(self._key_decisions) if self._key_decisions else []

    @key_decisions.setter
    def key_decisions(self, value):
        self._key_decisions = json.dumps(value) if value is not None else None

    @property
    def action_items(self):
        return json.loads(self._action_items) if self._action_items else []

    @action_items.setter
    def action_items(self, value):
        self._action_items = json.dumps(value) if value is not None else None

    def to_dict(self):
        """Convert a database row back into a plain dict (same shape as the old JSON files)."""
        return {
            "id":              self.id,
            "meeting_title":   self.title,
            "meeting_date":    self.date,
            "meeting_timestamp": self.timestamp,
            "meeting_summary": self.meeting_summary,
            "participants":    self.participants,
            "key_decisions":   self.key_decisions,
            "action_items":    self.action_items,
            "transcript":      self.transcript,
            "source":          self.source,
            "status":          self.status,
            "filename":        self.filename,
            "audio_path":      self.audio_path,
            "_file":           self.filename,   # kept for backwards compatibility
        }
