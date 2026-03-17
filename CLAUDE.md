# AI Meeting Assistant — Claude Context

## Project
FastAPI web app that transcribes, summarises, and queries meeting recordings.
- **Location:** `C:\Users\itchjc\Documents\Projects\ai-meeting-assistant`
- **GitHub:** https://github.com/CosmicSymphony/ai-meeting-assistant
- **Run:** `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
  - If port 8000 is taken (ghost python.exe processes), kill all with `taskkill /F /IM python.exe` then pick any free port (8001, 8002, etc.)
- **Python:** 3.14 at `C:\Users\itchjc\AppData\Local\Python\bin\python.exe`
- **No virtual environment** — packages installed globally

## Tech Stack
- **Backend:** FastAPI + SQLAlchemy ORM (SQLite locally, PostgreSQL via `DATABASE_URL` env var)
- **Transcription:** AssemblyAI REST API (`/v2/` endpoints)
- **LLM:** OpenAI gpt-4o
- **Meeting bot:** Recall.ai (Teams integration working end-to-end)
- **Templates:** Jinja2, static CSS at `app/static/style.css`

## API Keys (in `app/.env`)
- `ASSEMBLYAI_API_KEY` — set
- `OPENAI_API_KEY` — set
- `RECALLAI_API_KEY` — set (Asia Pacific region: `ap-northeast-1`)
- `DATABASE_URL` — blank = SQLite; set for PostgreSQL
- `WEBHOOK_BASE_URL` — blank locally; set on deployment for Recall.ai webhooks

## Bot Flow (end-to-end, working as of 2026-03-17)
1. User pastes Teams meeting URL → app calls Recall.ai to send bot
2. Bot joins meeting, waits in waiting room (user must admit it), records
3. When call ends, `session.status = "processing"` set immediately, background task fires
4. Background task: fetch Recall.ai transcript (usually empty) → fallback: download S3 video → upload bytes to AssemblyAI → poll until complete → OpenAI summary → save Meeting → `session.status = "done"`
5. Bot status page auto-refreshes every 5s until done or failed

## AssemblyAI Critical Notes
- Use `speech_models: ["universal-2"]` (plural, list) — `speech_model` (singular) is deprecated and causes 400
- `"best"` is NOT a valid value — use `"universal-2"` or `"universal-3-pro"`
- Must download S3 pre-signed URL first (via httpx), then upload bytes — passing URL directly causes 400
- All httpx clients use `verify=False` (corporate SSL proxy)
- Meetings must have actual speech — silent recordings return 0 chars and are marked failed

## Recall.ai Notes
- Base URL: `https://ap-northeast-1.recall.ai/api/v1`
- `transcription_options` not allowed on this account tier — omit from bot creation
- Transcript endpoint: `GET /transcript/?bot_id=` (paginated, returns `{results: [...]}`)
- Recording URL in: `bot.recordings[].media_shortcuts.video_mixed.data.download_url`

## Background Processing Pattern
- `session.status` guard: only trigger background task if status not in `("processing", "done", "failed")`
- Check recall_status BEFORE overwriting session.status (race condition — fixed)
- Background task opens its own `SessionLocal()` DB session

## Key Files
- `app/routes/recall.py` — bot join, status page, webhook, background processing
- `app/services/recall_service.py` — Recall.ai API calls, transcript formatting, status labels
- `app/services/transcription_service.py` — AssemblyAI upload + poll
- `app/services/summarize_service.py` — OpenAI summarisation
- `app/templates/bot_status.html` — bot status page (auto-refresh, spinner states)
- `app/templates/meeting_detail.html` — meeting summary + transcript view

## Routes
- `/web/` — dashboard
- `/web/meeting/{filename}` — meeting detail
- `/recall/join-meeting` — POST to send bot
- `/recall/bot/{bot_id}` — status page
- `/recall/bot/{bot_id}/debug` — raw Recall.ai JSON
- `/recall/webhook` — Recall.ai webhook receiver

## Models
- `Organisation` — tenant with `api_key`
- `Meeting` — transcript, summary, participants, key_decisions, action_items, `org_id`, `source`
- `BotSession` — bot_id, status, meeting_id (FK set when processed), org_id

## Planned Next
- Upgrade AssemblyAI to `universal-3-pro` for better accuracy
- Deploy to Railway (PostgreSQL + public webhook URL)
- Zoom and Google Meet support via Recall.ai
- Calendar auto-join (Azure AD / Microsoft Graph)
- SSO / enterprise auth
