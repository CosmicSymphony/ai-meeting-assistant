"""
Microsoft Graph API integration for calendar-based bot auto-join.
Uses MSAL client credentials flow (app-only auth, no user login required).
"""

import time
import httpx
import msal
from bs4 import BeautifulSoup
from app.config import settings

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_token_cache: dict = {}


def _get_access_token() -> str:
    """Obtain (or return cached) application access token via MSAL client credentials."""
    if _token_cache.get("access_token") and time.time() < _token_cache.get("expires_at", 0) - 60:
        return _token_cache["access_token"]

    app = msal.ConfidentialClientApplication(
        client_id=settings.AZURE_CLIENT_ID,
        client_credential=settings.AZURE_CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{settings.AZURE_TENANT_ID}",
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(f"MSAL token error: {result.get('error_description')}")

    _token_cache["access_token"] = result["access_token"]
    _token_cache["expires_at"] = time.time() + result.get("expires_in", 3600)
    return result["access_token"]


async def create_calendar_subscription(notification_url: str) -> dict:
    """Subscribe to calendar change notifications for the bot mailbox."""
    from datetime import datetime, timedelta, timezone
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=4229)).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = {
        "changeType": "created,updated",
        "notificationUrl": notification_url,
        "resource": f"/users/{settings.BOT_EMAIL}/events",
        "expirationDateTime": expiry,
        "clientState": settings.AZURE_CLIENT_SECRET[:16],
    }
    token = _get_access_token()
    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        resp = await client.post(
            f"{_GRAPH_BASE}/subscriptions",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        if resp.status_code >= 400:
            print(f"[Graph] Subscription error {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        return resp.json()


async def renew_calendar_subscription(subscription_id: str) -> dict:
    """Extend an existing Graph subscription before it expires."""
    from datetime import datetime, timedelta, timezone
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=4229)).strftime("%Y-%m-%dT%H:%M:%SZ")
    token = _get_access_token()
    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        resp = await client.patch(
            f"{_GRAPH_BASE}/subscriptions/{subscription_id}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"expirationDateTime": expiry},
        )
        resp.raise_for_status()
        return resp.json()


async def get_event(event_id: str) -> dict:
    """Fetch a calendar event by ID from the bot mailbox."""
    token = _get_access_token()
    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        resp = await client.get(
            f"{_GRAPH_BASE}/users/{settings.BOT_EMAIL}/events/{event_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"$select": "id,subject,start,end,onlineMeeting,body,organizer,isCancelled"},
        )
        resp.raise_for_status()
        return resp.json()


async def accept_event(event_id: str) -> None:
    """Send an accept response to a calendar invite (without sending a response email)."""
    token = _get_access_token()
    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        resp = await client.post(
            f"{_GRAPH_BASE}/users/{settings.BOT_EMAIL}/events/{event_id}/accept",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"sendResponse": False, "comment": ""},
        )
        resp.raise_for_status()


def extract_join_url(event: dict) -> str | None:
    """
    Extract the Teams join URL from a Graph calendar event.
    Tries onlineMeeting.joinUrl first, then parses the HTML body as a fallback.
    """
    join_url = (event.get("onlineMeeting") or {}).get("joinUrl")
    if join_url:
        return join_url

    body_content = (event.get("body") or {}).get("content", "")
    if body_content:
        soup = BeautifulSoup(body_content, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "teams.microsoft.com/l/meetup-join" in href:
                return href
    return None
