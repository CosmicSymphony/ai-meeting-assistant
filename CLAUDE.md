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

## Tests
There are no automated tests in this project.

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
- `DATABASE_URL` — blank = SQLite locally; must be set to PostgreSQL URL on Railway (reference the Postgres plugin)
- `WEBHOOK_BASE_URL` — blank locally; `https://ai-meeting-assistant-production-3552.up.railway.app` on Railway
- `AZURE_TENANT_ID` — Azure AD tenant ID
- `AZURE_CLIENT_ID` — Azure AD app registration client ID (`b0869b95-93d9-45bd-8dc4-1d2d9f25ec09`)
- `AZURE_CLIENT_SECRET` — Azure AD client secret
- `BOT_EMAIL` — shared mailbox email (`meetingbot@jpuniversal.com.sg`)
- `CALENDAR_WEBHOOK_SECRET` — dedicated secret for validating Graph calendar webhook notifications (set to a random string via `openssl rand -hex 32`; falls back to `AZURE_CLIENT_SECRET` if unset — add to Railway)
- `SSL_VERIFY` — set to `false` in local `.env` only when behind a corporate SSL proxy; always `true` (default) in production

## Architecture
**Service-Repository-Model pattern:**
- `app/models.py` — SQLAlchemy ORM models
- `app/repositories/` — data access with 30s in-memory cache per org
- `app/services/` — business logic and external API calls
- `app/routes/` — FastAPI endpoints delegating to services

**Multi-tenancy:** Every `Meeting`, `BotSession`, and `ScheduledMeeting` is scoped to an `Organisation` by `org_id`. A default org is auto-created at startup. Web UI uses the default org; REST API uses `X-API-Key` header.

**LLM abstraction:** `app/llm/provider_factory.py` returns a singleton `BaseProvider`. Currently hardcoded to OpenAI but designed for swappable backends.

**Database migrations:** Alembic for PostgreSQL; SQLite schema changes go in the `_migrate()` function in `app/database.py`. New tables are auto-created by `Base.metadata.create_all()`.

**FastAPI lifespan:** `app/main.py` uses `@asynccontextmanager async def lifespan()` for startup/shutdown. Startup: init DB, start APScheduler, reschedule pending meetings, start polling job, set up Graph subscription (delayed 15s so server is ready).

## Calendar Auto-Join Flow (working as of 2026-03-19)
1. User invites `meetingbot@jpuniversal.com.sg` to a Teams meeting
2. Microsoft Graph sends notification to `/calendar/webhook`
3. App checks DB first — if meeting already `completed/failed/cancelled`, exits immediately (no Graph API call)
4. If new: fetches event, accepts invite (once only — `is_new` guard), creates `ScheduledMeeting`, schedules APScheduler job at `start_time - 1 minute`
5. If existing + unchanged: exits silently (no update, no reschedule — prevents log spam from repeated Graph notifications)
6. At scheduled time: `create_bot()` fires → `BotSession` created → Recall.ai flow handles recording + summary

**Key notes:**
- Graph subscription set up 15s after startup (avoids 502 during validation handshake)
- On redeploy: lists existing subscriptions, reuses matching one or deletes stale ones before creating new
- Graph fires many notifications per event — duplicate guard: DB check first, then `is_new` flag, accept only once
- Shared mailbox (`meetingbot@`) cannot use `AutomateProcessing AutoAccept` (Exchange limitation). "Didn't respond" in Teams UI is cosmetic — bot still joins.
- `ScheduledMeeting.status`: `scheduled` → `completed` (bot dispatched) or `failed` or `cancelled`

## Manual Bot Flow (end-to-end, working)
1. User pastes Teams meeting URL → app calls Recall.ai to send bot
2. Bot joins meeting, waits in waiting room (user must admit it), records
3. When call ends → webhook fires OR polling fallback catches it within 1 minute
4. Background task: fetch Recall.ai transcript (usually empty) → fallback: download S3 video → upload bytes to AssemblyAI → poll until complete → OpenAI summary → save Meeting → `session.status = "done"`
5. Bot status page auto-refreshes every 5s until done or failed

## Polling Fallback (critical — Recall.ai webhooks are unreliable)
`app/services/bot_processing_service.py` contains the shared bot processing logic.
- APScheduler runs `_poll_pending_bots_job` every **1 minute**
- Queries all `BotSession` records not in (`done`, `failed`, `processing`) with no `meeting_id`, created within last 24h
- Calls Recall.ai API for each — if status is `done`/`call_ended`, triggers `process_bot_session()`
- This is the primary reliability mechanism — do not remove it
- `everyone_left_timeout` is set to **120 seconds** on bot creation so bot exits 2 minutes after last participant leaves

## Webhook Race Condition Fix (2026-03-19)
In `routes/recall.py` webhook handler, `should_process` must be evaluated BEFORE updating `session.status`. The old code set `session.status = "done"` first, then the check excluded `"done"` — so background processing never ran.

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
- `everyone_left_timeout: 120` — bot exits 2 minutes after last participant leaves
- Recall.ai webhook delivery is unreliable — always rely on the polling fallback, not just the webhook

## Security Hardening

### Prompt Injection (2026-03-19)
All LLM prompts wrap untrusted content in XML delimiters (`<transcript>`, `<question>`, `<meeting_data>`, `<signature>`).
- System message explicitly instructs model to treat tagged content as data only, never as instructions
- `tone` and `audience` in email generation are allowlisted (`_ALLOWED_TONES`, `_ALLOWED_AUDIENCES`)
- User questions capped at 500 chars, signatures at 200 chars

### HTTP Security (2026-03-20)
- Security headers middleware in `main.py`: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`
- `Strict-Transport-Security` added automatically when `WEBHOOK_BASE_URL` is set (production only)
- `meeting_url` validated before sending to Recall.ai — only `https://` URLs from `teams.microsoft.com`, `zoom.us`, `meet.google.com` are allowed
- File uploads validated by extension: audio endpoints accept `.mp3/.mp4/.m4a/.wav/.webm/.ogg/.flac/.aac`; transcript endpoint accepts `.txt/.text` only
- `/recall/bot/{id}/debug` requires `X-API-Key` header
- Recall.ai and calendar webhooks handle malformed JSON gracefully (no 500)
- `CALENDAR_WEBHOOK_SECRET` used as Graph clientState (separate from Azure auth credentials)
- `SSL_VERIFY` env var controls outbound SSL verification — always `true` in production

### Known gaps (planned)
- Web UI has no authentication — all routes use the default org (SSO/login not yet built)
- No rate limiting on cost-intensive endpoints (`/transcribe-audio`, `/summarize`, `/ask_meetings`)

## Timezone
- Meeting timestamps stored in **SGT (Asia/Singapore, UTC+8)** using `ZoneInfo("Asia/Singapore")`
- Railway servers run in UTC — always use explicit timezone, never `datetime.now()` without tz

## Background Processing Pattern
- `session.status` guard: only trigger background task if status not in `("processing", "done", "failed")`
- Evaluate `should_process` BEFORE updating `session.status` (race condition — fixed 2026-03-19)
- All background tasks open their own `SessionLocal()` DB session
- Extract ORM attribute values (bot_id, org_id) into local variables BEFORE closing the DB session to avoid `DetachedInstanceError`

## Key Files
- `app/main.py` — FastAPI app entry point; lifespan (DB init, scheduler start, Graph subscription), top-level routes
- `app/config.py` — `Settings` class (loads `.env` via `python-dotenv`); import with `from app.config import settings`
- `app/dependencies.py` — FastAPI dependency injection (DB session, org resolution from `X-API-Key`)
- `app/routes/recall.py` — bot join, status page, webhook, background processing
- `app/routes/web.py` — dashboard, upload, transcription, Q&A, email generation
- `app/routes/calendar.py` — Graph webhook, subscription setup, notification handler
- `app/scheduler.py` — APScheduler setup, bot deployment jobs, polling fallback, startup rescheduling
- `app/services/bot_processing_service.py` — shared bot processing logic (transcript → AssemblyAI → OpenAI → save)
- `app/services/graph_service.py` — Microsoft Graph API: token, subscribe, get/accept event, extract join URL
- `app/services/recall_service.py` — Recall.ai API calls, transcript formatting, status labels
- `app/services/transcription_service.py` — AssemblyAI upload + poll
- `app/services/summarize_service.py` — OpenAI summarisation
- `app/services/ask_meetings_service.py` — multi-meeting Q&A with date/person/keyword search
- `app/schemas/email_schemas.py` — Pydantic request/response models for email generation endpoints
- `app/templates/bot_status.html` — bot status page (auto-refresh, spinner states)
- `app/templates/meeting_detail.html` — meeting summary + transcript view

## Routes
Routes in `app/routes/`:
- `/web/` — dashboard
- `/web/meeting/{filename}` — meeting detail
- `/recall/join-meeting` — POST to send bot
- `/recall/bot/{bot_id}` — status page
- `/recall/bot/{bot_id}/debug` — raw Recall.ai JSON
- `/recall/webhook` — Recall.ai webhook receiver
- `/calendar/webhook` — Microsoft Graph calendar notification receiver
- `/calendar/subscribe` — POST to manually create/refresh Graph subscription

Routes defined directly in `app/main.py`:
- `POST /generate_followup_email` — generate follow-up email from a specific meeting
- `POST /generate_followup_email_latest` — generate from the most recent meeting
- `POST /summarize` — summarize an uploaded transcript file
- `POST /ask_meetings` — multi-meeting natural-language Q&A

## Models
- `Organisation` — tenant with `api_key`
- `Meeting` — transcript, summary, participants, key_decisions, action_items, `org_id`, `source`
- `BotSession` — bot_id, status, meeting_id (FK set when processed), org_id, created_at
- `ScheduledMeeting` — graph_event_id (unique), subject, start_time (naive UTC), join_url, organizer_email, status, bot_session_id (FK), org_id

## UI Notes
- `input[type="url"]` is explicitly styled in `style.css` alongside `input[type="text"]` — both share the same base/focus styles
- Upload areas (`.upload-area`) disable `pointer-events` once a file is selected to prevent accidental re-click; restored on remove
- `showFilename()` in `index.html` handles all upload state: hides drag/drop label+icon, shows green tick + filename + remove button, locks area
- Meeting name input removed from the join-meeting form — backend defaults to `"Teams Meeting"`
- Meeting detail badges: first = date, second = time only (split from `meeting_timestamp`)
- Summary bullet points split on `•` character and rendered as `<ul>` in both `index.html` and `meeting_detail.html`

## Planned Next

### In-Meeting Chat Message + Opt-Out Feature (next to build)
Read.ai-style: when bot enters `in_call_recording` state, send a Teams chat message:
> "AI Meeting Assistant has joined and is recording. To opt out: <a href="{WEBHOOK_BASE_URL}/optout/{bot_id}">Opt Out</a>"

**Files to modify:**
- `app/services/recall_service.py` — add `send_chat_message(bot_id, message)` and `stop_bot(bot_id)`
- `app/routes/recall.py` — trigger chat message when webhook status = `in_call_recording`
- `app/models.py` — add `chat_notified` bool column to `BotSession` (prevent duplicate messages)
- `app/database.py` — add `chat_notified` to `_migrate()`
- `app/templates/optout.html` — simple opt-out page with Stop Recording button
- Register `GET/POST /optout/{bot_id}` route (public, no auth)

**Recall.ai chat endpoint:** `POST https://ap-northeast-1.recall.ai/api/v1/bot/{bot_id}/send_chat_message/`
Teams supports HTML anchor tags only. No tier restrictions.

**Decisions needed before building:**
- Privacy policy URL (to include in the chat message)
- Should opt-out delete the saved recording from DB, or just stop the bot?

### Other roadmap items
- Upgrade AssemblyAI to `universal-3-pro` for better accuracy
- Zoom and Google Meet support via Recall.ai
- Convert `meetingbot@` shared mailbox to a resource mailbox for proper auto-accept in Teams UI
- SSO / enterprise auth
- Multi-tenant SaaS: OAuth consent flow per customer, per-org Azure credentials
