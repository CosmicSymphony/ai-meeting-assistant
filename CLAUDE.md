# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project
FastAPI web app that transcribes, summarises, and queries meeting recordings.
- **Location:** `C:\Users\itchjc\Documents\Projects\ai-meeting-assistant`
- **GitHub:** https://github.com/CosmicSymphony/ai-meeting-assistant
- **Production:** `https://ai-meeting-assistant-production-3552.up.railway.app/web/`
- **Run locally:** `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
  - If port 8000 is taken (ghost python.exe processes), kill with `taskkill /F /IM python.exe` then pick any free port
- **Python:** 3.14 at `C:\Users\itchjc\AppData\Local\Python\bin\python.exe`
- **No virtual environment** — packages installed globally

## Tech Stack
- **Backend:** FastAPI + SQLAlchemy ORM (SQLite locally, PostgreSQL via `DATABASE_URL` env var)
- **Transcription:** AssemblyAI REST API (`/v2/` endpoints)
- **LLM:** OpenAI gpt-4o via `app/llm/openai_provider.py` (abstracted behind `BaseProvider`)
- **Meeting bot:** Recall.ai (Teams integration working end-to-end)
- **Calendar integration:** Microsoft Graph API + MSAL (auto-accept invites, schedule bot)
- **Scheduler:** APScheduler `AsyncIOScheduler` — deploys bot 1 min before meeting start
- **Templates:** Jinja2, static CSS at `app/static/style.css`
- **Deployment:** Railway (PostgreSQL + auto-deploy from GitHub)

## Environment Variables
Local: `app/.env`. Production: Railway Variables tab.
- `ASSEMBLYAI_API_KEY` — AssemblyAI transcription
- `OPENAI_API_KEY` — OpenAI gpt-4o
- `RECALLAI_API_KEY` — Recall.ai (Asia Pacific region: `ap-northeast-1`)
- `DATABASE_URL` — blank = SQLite locally; auto-set by Railway PostgreSQL plugin
- `WEBHOOK_BASE_URL` — blank locally; `https://ai-meeting-assistant-production-3552.up.railway.app` on Railway
- `AZURE_TENANT_ID` — Azure AD tenant ID
- `AZURE_CLIENT_ID` — Azure AD app registration client ID (`b0869b95-93d9-45bd-8dc4-1d2d9f25ec09`)
- `AZURE_CLIENT_SECRET` — Azure AD client secret
- `BOT_EMAIL` — shared mailbox email (`meetingbot@jpuniversal.com.sg`)

## Architecture
**Service-Repository-Model pattern:**
- `app/models.py` — SQLAlchemy ORM models
- `app/repositories/` — data access with 30s in-memory cache per org
- `app/services/` — business logic and external API calls
- `app/routes/` — FastAPI endpoints delegating to services

**Multi-tenancy:** Every `Meeting`, `BotSession`, and `ScheduledMeeting` is scoped to an `Organisation` by `org_id`. A default org is auto-created at startup. Web UI uses the default org; REST API uses `X-API-Key` header.

**LLM abstraction:** `app/llm/provider_factory.py` returns a singleton `BaseProvider`. Currently hardcoded to OpenAI but designed for swappable backends.

**Database migrations:** Alembic for PostgreSQL; SQLite schema changes go in the `_migrate()` function in `app/database.py`. New tables are auto-created by `Base.metadata.create_all()`.

**FastAPI lifespan:** `app/main.py` uses `@asynccontextmanager async def lifespan()` for startup/shutdown. Startup: init DB, start APScheduler, reschedule pending meetings, set up Graph subscription (delayed 15s so server is ready).

## Calendar Auto-Join Flow (working as of 2026-03-18)
1. User invites `meetingbot@jpuniversal.com.sg` to a Teams meeting
2. Microsoft Graph sends notification to `/calendar/webhook`
3. App fetches event details, accepts invite (once only — race condition guarded by DB unique constraint on `graph_event_id`)
4. `ScheduledMeeting` record created, APScheduler job scheduled at `start_time - 1 minute`
5. At scheduled time: `create_bot()` fires → `BotSession` created → existing Recall.ai flow handles recording + summary

**Key notes:**
- Graph subscription is set up 15s after startup (avoids 502 during validation handshake)
- On redeploy: lists existing subscriptions, reuses matching one or deletes stale ones before creating new
- Graph fires multiple notifications per event — duplicate guard: insert DB record first, only accept if insert succeeds
- Shared mailbox (`meetingbot@`) cannot use `AutomateProcessing AutoAccept` (Exchange limitation — only resource mailboxes support this). "Didn't respond" in Teams UI is cosmetic only — bot still joins.
- `ScheduledMeeting.status`: `scheduled` → `completed` (bot dispatched) or `failed` or `cancelled`

## Manual Bot Flow (end-to-end, working)
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
- Meetings with no speech or music-only audio are marked failed with a user-friendly message

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
- `app/routes/web.py` — dashboard, upload, transcription, Q&A, email generation
- `app/routes/calendar.py` — Graph webhook, subscription setup, notification handler
- `app/scheduler.py` — APScheduler setup, bot deployment jobs, startup rescheduling
- `app/services/graph_service.py` — Microsoft Graph API: token, subscribe, get/accept event, extract join URL
- `app/services/recall_service.py` — Recall.ai API calls, transcript formatting, status labels
- `app/services/transcription_service.py` — AssemblyAI upload + poll
- `app/services/summarize_service.py` — OpenAI summarisation
- `app/services/ask_meetings_service.py` — multi-meeting Q&A with date/person/keyword search
- `app/templates/bot_status.html` — bot status page (auto-refresh, spinner states)
- `app/templates/meeting_detail.html` — meeting summary + transcript view

## Routes
- `/web/` — dashboard
- `/web/meeting/{filename}` — meeting detail
- `/recall/join-meeting` — POST to send bot
- `/recall/bot/{bot_id}` — status page
- `/recall/bot/{bot_id}/debug` — raw Recall.ai JSON
- `/recall/webhook` — Recall.ai webhook receiver
- `/calendar/webhook` — Microsoft Graph calendar notification receiver
- `/calendar/subscribe` — POST to manually create/refresh Graph subscription

## Models
- `Organisation` — tenant with `api_key`
- `Meeting` — transcript, summary, participants, key_decisions, action_items, `org_id`, `source`
- `BotSession` — bot_id, status, meeting_id (FK set when processed), org_id
- `ScheduledMeeting` — graph_event_id (unique), subject, start_time (naive UTC), join_url, organizer_email, status, bot_session_id (FK), org_id

## UI Notes
- `input[type="url"]` is explicitly styled in `style.css` alongside `input[type="text"]` — both share the same base/focus styles
- Upload areas (`.upload-area`) disable `pointer-events` once a file is selected to prevent accidental re-click; restored on remove
- `showFilename()` in `index.html` handles all upload state: hides drag/drop label+icon, shows green tick + filename + remove button, locks area
- Meeting name input removed from the join-meeting form — backend defaults to `"Teams Meeting"`
- Meeting detail badges: first = date, second = time only (split from `meeting_timestamp`)
- Summary bullet points split on `•` character and rendered as `<ul>` in both `index.html` and `meeting_detail.html`

## Planned Next
- Upgrade AssemblyAI to `universal-3-pro` for better accuracy
- Zoom and Google Meet support via Recall.ai
- Convert `meetingbot@` shared mailbox to a resource mailbox for proper auto-accept in Teams UI
- SSO / enterprise auth
- Multi-tenant SaaS: OAuth consent flow per customer, per-org Azure credentials
