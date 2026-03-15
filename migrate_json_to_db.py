"""
One-time migration script.
Reads all JSON files from /outputs/ and inserts them into meetings.db
Safe to run multiple times — skips files already imported.
"""

import json
from pathlib import Path
from app.database import init_db, SessionLocal
from app.models import Meeting

OUTPUTS_DIR = Path("outputs")


def migrate():
    # Make sure the table exists
    init_db()

    db = SessionLocal()

    json_files = list(OUTPUTS_DIR.glob("*.json"))

    if not json_files:
        print("No JSON files found in /outputs/ — nothing to migrate.")
        return

    imported = 0
    skipped  = 0

    for file_path in json_files:
        # Skip if already imported (check by filename)
        existing = db.query(Meeting).filter_by(filename=file_path.name).first()
        if existing:
            print(f"  SKIP  {file_path.name}  (already in database)")
            skipped += 1
            continue

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            meeting = Meeting()
            meeting.title          = data.get("meeting_title")
            meeting.date           = data.get("meeting_date")
            meeting.timestamp      = data.get("meeting_timestamp")
            meeting.transcript     = data.get("transcript")
            meeting.meeting_summary = data.get("meeting_summary")
            meeting.participants   = data.get("participants", [])
            meeting.key_decisions  = data.get("key_decisions", [])
            meeting.action_items   = data.get("action_items", [])
            meeting.filename       = file_path.name
            meeting.source         = "upload"
            meeting.status         = "ready"

            db.add(meeting)
            db.commit()

            print(f"  OK    {file_path.name}  ->  id={meeting.id}")
            imported += 1

        except Exception as e:
            db.rollback()
            print(f"  FAIL  {file_path.name}  —  {e}")

    db.close()
    print(f"\nDone. {imported} imported, {skipped} skipped.")


if __name__ == "__main__":
    migrate()
