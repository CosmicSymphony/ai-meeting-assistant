import asyncio
import httpx
from app.config import settings

_ASSEMBLYAI_BASE = "https://api.assemblyai.com/v2"
_HEADERS = {"authorization": settings.ASSEMBLYAI_API_KEY}


async def transcribe_audio(file_bytes: bytes, filename: str, language: str = None) -> tuple[str, str]:
    """
    Transcribe audio via AssemblyAI REST API directly (bypasses SDK model mismatch).
    Returns (transcript_text_with_speaker_labels, detected_language).
    """
    async with httpx.AsyncClient(timeout=300) as client:

        # 1. Upload the audio file
        upload_resp = await client.post(
            f"{_ASSEMBLYAI_BASE}/upload",
            headers=_HEADERS,
            content=file_bytes,
        )
        upload_resp.raise_for_status()
        audio_url = upload_resp.json()["upload_url"]

        # 2. Submit transcription job
        payload = {
            "audio_url": audio_url,
            "speech_models": ["universal-3-pro"],
            "speaker_labels": True,
            "punctuate": True,
            "format_text": True,
        }
        if language:
            payload["language_code"] = language

        submit_resp = await client.post(
            f"{_ASSEMBLYAI_BASE}/transcript",
            headers={**_HEADERS, "content-type": "application/json"},
            json=payload,
        )
        submit_resp.raise_for_status()
        transcript_id = submit_resp.json()["id"]

        # 3. Poll until complete
        while True:
            poll_resp = await client.get(
                f"{_ASSEMBLYAI_BASE}/transcript/{transcript_id}",
                headers=_HEADERS,
            )
            poll_resp.raise_for_status()
            data = poll_resp.json()

            status = data["status"]
            if status == "completed":
                break
            if status == "error":
                raise RuntimeError(f"AssemblyAI transcription failed: {data.get('error')}")

            await asyncio.sleep(3)

    # 4. Format with speaker labels if available
    utterances = data.get("utterances") or []
    if utterances:
        lines = [f"Speaker {u['speaker']}: {u['text']}" for u in utterances]
        text = "\n".join(lines)
    else:
        text = data.get("text") or ""

    detected_language = data.get("language_code") or language or "unknown"
    return text.strip(), detected_language
