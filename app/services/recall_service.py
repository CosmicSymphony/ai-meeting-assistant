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
        "call_ended":             "Call ended, processing…",
        "done":                   "Done",
        "fatal":                  "Failed",
    }.get(status_code, status_code)
