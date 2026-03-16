import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

_DEFAULT_SQLITE = f"sqlite:///{Path(__file__).parent.parent / 'meetings.db'}"


class Settings:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
    RECALLAI_API_KEY = os.getenv("RECALLAI_API_KEY")
    DATABASE_URL = os.getenv("DATABASE_URL") or _DEFAULT_SQLITE
    WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "")  # e.g. https://yourapp.railway.app


settings = Settings()