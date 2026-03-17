import httpx
from app.config import settings

_BASE = "https://ap-northeast-1.recall.ai/api/v1"
_HEADERS = {
    "Authorization": f"Token {settings.RECALLAI_API_KEY}",
    "Content-Type": "application/json",
}


def _client() -> httpx.AsyncClient:
    """HTTP client with SSL verification disabled for corporate proxy compatibility."""
    return httpx.AsyncClient(timeout=30, verify=False)


async def create_bot(meeting_url: str, bot_name: str = "AI Meeting Assistant", webhook_url: str = None) -> dict:
    """Send a bot to a Teams meeting. Returns the full bot object from Recall.ai."""
    payload = {
        "meeting_url": meeting_url,
        "bot_name": bot_name,
    }
    if webhook_url:
        payload["webhook_url"] = webhook_url

    async with _client() as client:
        resp = await client.post(f"{_BASE}/bot/", headers=_HEADERS, json=payload)
        resp.raise_for_status()
        return resp.json()


async def get_bot(bot_id: str) -> dict:
    """Get current status and metadata of a bot."""
    async with _client() as client:
        resp = await client.get(f"{_BASE}/bot/{bot_id}/", headers=_HEADERS)
        resp.raise_for_status()
        return resp.json()


async def get_bot_transcript(bot_id: str) -> list:
    """Get the transcript segments for a completed bot."""
    async with _client() as client:
        resp = await client.get(f"{_BASE}/transcript/?bot_id={bot_id}", headers=_HEADERS)
        resp.raise_for_status()
        data = resp.json()
        # New endpoint returns paginated {results: [...]}
        if isinstance(data, dict):
            return data.get("results", [])
        return data


async def get_bot_recording_url(bot_id: str) -> str | None:
    """
    Get the audio/video recording download URL for a completed bot.
    Recall.ai returns recording URLs in the bot object under `recordings` or `video_url`.
    Returns the first available download URL, or None if not available.
    """
    bot_data = await get_bot(bot_id)

    # Try `recordings` array first (newer Recall.ai API)
    recordings = bot_data.get("recordings") or []
    for rec in recordings:
        url = rec.get("media_shortcuts", {}).get("video_mixed", {}).get("data", {}).get("download_url")
        if not url:
            url = rec.get("download_url")
        if url:
            return url

    # Fallback: top-level video_url field
    return bot_data.get("video_url") or None


def format_transcript(raw_transcript: list) -> str:
    """
    Convert Recall.ai transcript segments into speaker-labelled text
    that our summarize service understands.

    Recall.ai format:
      [{"speaker": "John", "words": [{"text": "Hello", ...}, ...]}, ...]
    """
    lines = []
    for segment in raw_transcript:
        speaker = segment.get("speaker") or "Unknown"
        words = segment.get("words") or []
        text = " ".join(w.get("text", "") for w in words).strip()
        if text:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def get_bot_status_label(status_code: str) -> str:
    """Convert Recall.ai status codes to human-readable labels."""
    return {
        "created":                "Created",
        "joining_call":           "Joining meeting…",
        "in_waiting_room":        "In waiting room…",
        "in_call_not_recording":  "In call (not recording yet)",
        "in_call_recording":      "Recording…",
        "call_ended":             "Call ended",
        "processing":             "Generating transcript and summary…",
        "done":                   "Summary ready ✓",
        "fatal":                  "Failed (bot error)",
        "failed":                 "Failed (processing error)",
    }.get(status_code, status_code)
