from openai import OpenAI
from app.config import settings

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def transcribe_audio(file_bytes: bytes, filename: str) -> str:
    """
    Send audio file to OpenAI Whisper and return the transcript text.
    Supported formats: mp3, mp4, mpeg, mpga, m4a, wav, webm (max 25MB).
    """
    client = _get_client()

    response = client.audio.transcriptions.create(
        model="whisper-1",
        file=(filename, file_bytes),
        language="en",
    )

    return response.text.strip()
