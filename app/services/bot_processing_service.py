"""
Shared background processing for completed Recall.ai bot sessions.
Used by both the webhook handler and the polling fallback.
"""
# Recall.ai status codes that mean the call has finished and is ready to process.
# Imported by recall.py and scheduler.py to keep the set in one place.
DONE_STATUSES = {"done", "call_ended"}

from app.database import SessionLocal
from app.models import BotSession, Meeting
from app.services.recall_service import get_bot_transcript, format_transcript, get_bot_recording_url
from app.services.transcription_service import transcribe_from_url
from app.services.summarize_service import summarize_meeting


async def process_bot_session(bot_id: str, org_id: int) -> None:
    """Fetch transcript, run AssemblyAI fallback if needed, generate summary, save Meeting."""
    print(f"[Recall] Starting background processing for bot {bot_id}")
    db = SessionLocal()
    try:
        session = db.query(BotSession).filter_by(bot_id=bot_id).first()
        if not session:
            print(f"[Recall] No session found for bot {bot_id}")
            return

        # Try Recall.ai's own real-time transcript first
        print(f"[Recall] Fetching transcript for bot {bot_id}...")
        raw = await get_bot_transcript(bot_id)
        print(f"[Recall] Recall.ai transcript segments: {len(raw)}")
        transcript_text = format_transcript(raw)
        print(f"[Recall] Formatted transcript length: {len(transcript_text)} chars")

        # If empty, fall back to AssemblyAI using the recording file
        if not transcript_text.strip():
            print("[Recall] Recall.ai transcript empty, trying AssemblyAI fallback...")
            recording_url = await get_bot_recording_url(bot_id)
            print(f"[Recall] Recording URL: {recording_url}")
            if recording_url:
                try:
                    transcript_text, lang = await transcribe_from_url(recording_url)
                    print(f"[Recall] AssemblyAI transcription done. Language: {lang}, Length: {len(transcript_text)} chars")
                except Exception as e:
                    print(f"[Recall] AssemblyAI transcription failed: {e}")
            else:
                print("[Recall] No recording URL available.")

        if not transcript_text or not transcript_text.strip():
            print(f"[Recall] No transcript available for bot {bot_id} — marking failed.")
            session.status = "failed"
            db.commit()
            return

        print(f"[Recall] Generating summary for bot {bot_id}...")
        summary = await summarize_meeting(transcript_text, org_id)

        meeting_id = summary.get("id")
        if meeting_id:
            meeting = db.query(Meeting).filter_by(id=meeting_id).first()
            if meeting:
                meeting.source = "teams"
                session.meeting_id = meeting.id
        session.status = "done"
        db.commit()
        print(f"[Recall] Meeting processed successfully: {summary.get('_file')} (id={meeting_id})")

    except Exception as e:
        import traceback
        print(f"[Recall] Processing EXCEPTION for bot {bot_id}: {e}")
        traceback.print_exc()
        try:
            db.rollback()
            session = db.query(BotSession).filter_by(bot_id=bot_id).first()
            if session:
                session.status = "failed"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
