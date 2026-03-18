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

    # Microsoft Graph / Azure AD (for calendar auto-join)
    AZURE_TENANT_ID     = os.getenv("AZURE_TENANT_ID")
    AZURE_CLIENT_ID     = os.getenv("AZURE_CLIENT_ID")
    AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
    BOT_EMAIL           = os.getenv("BOT_EMAIL", "")


settings = Settings()