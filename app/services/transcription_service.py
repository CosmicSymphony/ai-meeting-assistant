from openai import OpenAI
from app.config import settings

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def transcribe_audio(file_bytes: bytes, filename: str, language: str = "en") -> tuple[str, str]:
    """
    Send audio file to OpenAI Whisper and return (transcript_text, detected_language).
    Pass a BCP-47 language code (e.g. 'en', 'ms', 'zh') to override auto-detection.
    Supported formats: mp3, mp4, mpeg, mpga, m4a, wav, webm (max 25MB).
    """
    client = _get_client()

    kwargs = {
        "model": "whisper-1",
        "file": (filename, file_bytes),
        "response_format": "verbose_json",
    }
    if language:
        kwargs["language"] = language

    response = client.audio.transcriptions.create(**kwargs)

    transcript = response.text.strip()
    detected = response.language or language or "unknown"

    return transcript, detected
