from __future__ import annotations

import json
from typing import Any, Dict

from app.llm.provider_factory import get_llm_provider


async def ask_single_meeting_question(meeting: Dict[str, Any], question: str) -> str:
    """
    Answer a user's question using only one meeting's data.
    """
    meeting_context = {
        "meeting_title": meeting.get("meeting_title", ""),
        "meeting_date": meeting.get("meeting_date", ""),
        "meeting_timestamp": meeting.get("meeting_timestamp", ""),
        "participants": meeting.get("participants", []),
        "meeting_summary": meeting.get("meeting_summary", ""),
        "key_decisions": meeting.get("key_decisions", []),
        "action_items": meeting.get("action_items", []),
        "transcript": meeting.get("transcript", ""),
    }

    prompt = f"""
Answer the user's question using ONLY the meeting data provided below.
Do not invent information.
If the answer is not found in the meeting, say:
"I could not find that in this meeting."

Keep the answer clear and concise.
If the answer involves action items, mention the owner and deadline when available.

Meeting data:
{json.dumps(meeting_context)}

User question:
{question}
"""

    provider = get_llm_provider()
    return (await provider.generate(prompt)).strip()
