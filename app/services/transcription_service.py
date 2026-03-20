import asyncio
import httpx
from app.config import settings

_ASSEMBLYAI_BASE = "https://api.assemblyai.com/v2"
_HEADERS = {"authorization": settings.ASSEMBLYAI_API_KEY}


async def _run_transcription(audio_url: str = None, file_bytes: bytes = None, language: str = None) -> tuple[str, str]:
    """Shared AssemblyAI transcription logic. Accepts either a URL or raw bytes."""
    async with httpx.AsyncClient(timeout=300, verify=settings.SSL_VERIFY) as client:

        # 1. Upload bytes if no URL provided
        if not audio_url:
            upload_resp = await client.post(
                f"{_ASSEMBLYAI_BASE}/upload",
                headers=_HEADERS,
                content=file_bytes,
            )
            if upload_resp.status_code >= 400:
                print(f"[AssemblyAI] Upload error {upload_resp.status_code}: {upload_resp.text}")
            upload_resp.raise_for_status()
            audio_url = upload_resp.json()["upload_url"]
            print(f"[AssemblyAI] Upload complete, url={audio_url[:60]}...")

        # 2. Submit transcription job
        payload = {
            "audio_url": audio_url,
            "speech_models": ["universal-2"],
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
        if submit_resp.status_code >= 400:
            print(f"[AssemblyAI] Submit error {submit_resp.status_code}: {submit_resp.text}")
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
                api_error = data.get("error") or ""
                if "no spoken audio" in api_error.lower() or "language_detection" in api_error.lower():
                    raise RuntimeError("Transcription failed: no spoken audio was detected in this file.")
                raise RuntimeError(f"Transcription failed: {api_error}")

            await asyncio.sleep(1)

    # 4. Format with speaker labels if available
    utterances = data.get("utterances") or []
    print(f"[AssemblyAI] Utterances: {len(utterances)}, raw text length: {len(data.get('text') or '')}")
    if utterances:
        lines = [f"Speaker {u['speaker']}: {u['text']}" for u in utterances]
        text = "\n".join(lines)
    else:
        text = data.get("text") or ""

    detected_language = data.get("language_code") or language or "unknown"
    return text.strip(), detected_language


async def transcribe_from_url(audio_url: str, language: str = None) -> tuple[str, str]:
    """
    Transcribe audio from a remote URL.
    Downloads the file first (handles pre-signed S3 URLs), then uploads bytes to AssemblyAI.
    Returns (transcript_text_with_speaker_labels, detected_language).
    """
    print(f"[AssemblyAI] Downloading audio from URL...")
    async with httpx.AsyncClient(timeout=300, verify=settings.SSL_VERIFY) as client:
        dl_resp = await client.get(audio_url)
        dl_resp.raise_for_status()
        file_bytes = dl_resp.content
    print(f"[AssemblyAI] Downloaded {len(file_bytes)} bytes, submitting for transcription...")
    return await _run_transcription(file_bytes=file_bytes, language=language)


async def transcribe_audio(file_bytes: bytes, filename: str, language: str = None) -> tuple[str, str]:
    """
    Transcribe audio via AssemblyAI REST API directly.
    Returns (transcript_text_with_speaker_labels, detected_language).
    """
    return await _run_transcription(file_bytes=file_bytes, language=language)
