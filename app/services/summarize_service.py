from app.llm.provider_factory import get_llm_provider
import json
import os
from datetime import datetime

def summarize_meeting(transcript: str):
    provider = get_llm_provider()

    prompt = f"""
You are an AI meeting assistant.

Analyze the meeting transcript and return ONLY valid JSON in this exact format:

{{
  "meeting_summary": "...",
  "key_decisions": ["...", "..."],
  "action_items": [
    {{
      "task": "...",
      "owner": "...",
      "deadline": "..."
    }}
  ],
  "deadlines": ["...", "..."],
  "risks": ["...", "..."]
}}

Transcript:
{transcript}
"""

    response = provider.generate(prompt)

    try:
        ai_result = json.loads(response)
    except json.JSONDecodeError:
        ai_result = {
            "meeting_summary": response,
            "key_decisions": [],
            "action_items": [],
            "deadlines": [],
            "risks": []
        }

    now = datetime.now()

    result = {
        "meeting_title": "Auto-generated meeting",
        "meeting_date": now.strftime("%Y-%m-%d"),
        "meeting_timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "participants": [],
        "transcript": transcript,
        "meeting_summary": ai_result.get("meeting_summary", ""),
        "key_decisions": ai_result.get("key_decisions", []),
        "action_items": ai_result.get("action_items", []),
        "deadlines": ai_result.get("deadlines", []),
        "risks": ai_result.get("risks", [])
    }

    os.makedirs("outputs", exist_ok=True)

    filename = f"meeting_summary_{now.strftime('%Y-%m-%d_%H-%M-%S')}.json"
    output_file = os.path.join("outputs", filename)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    result["saved_to"] = output_file

    return result