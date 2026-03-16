import re
import dateparser
from app.llm.provider_factory import get_llm_provider
from app.repositories.meeting_repository import (
    get_recent_meetings,
    search_meetings_by_person,
    search_meetings_by_keywords,
    search_meetings_by_date,
)


COMMON_STOPWORDS = {
    "what", "when", "where", "which", "who", "why", "how",
    "is", "are", "was", "were", "the", "a", "an",
    "in", "on", "at", "to", "for", "of", "and", "about",
    "did", "do", "does", "last", "latest", "previous",
    "meeting", "meetings", "task", "tasks"
}

_TRANSCRIPT_LIMIT = 2000  # max chars of transcript included in prompt

# Months and date-like patterns that indicate the question contains a date reference
_DATE_SIGNAL = re.compile(
    r"\b("
    r"january|february|march|april|may|june|july|august|september|october|november|december"
    r"|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"   # 10/3/2026 or 10-3-2026
    r"|\d{4}-\d{2}-\d{2}"                 # 2026-03-10
    r")\b",
    re.IGNORECASE,
)


def extract_date_from_question(question: str):
    """
    Return a datetime.date if the question contains a recognisable date reference,
    otherwise return None.

    dateparser handles natural language like:
      "10 march 2026", "March 10th", "10/3/2026", "last Monday", "yesterday"
    """
    if not _DATE_SIGNAL.search(question):
        return None  # skip dateparser if no date signal — avoids false positives

    parsed = dateparser.parse(
        question,
        settings={
            "PREFER_DAY_OF_MONTH": "first",
            "RETURN_AS_TIMEZONE_AWARE": False,
            "PREFER_LOCALE_DATE_ORDER": False,
        },
    )
    return parsed.date() if parsed else None


def extract_possible_person(question: str):
    # look for capitalized words in the original question
    matches = re.findall(r"\b[A-Z][a-z]+\b", question)
    if matches:
        return matches[0]

    # fallback for lowercase names like "sarah"
    known_names = ["john", "sarah", "david"]
    question_lower = question.lower()
    for name in known_names:
        if name in question_lower:
            return name

    return None


def extract_keywords(question: str):
    words = re.findall(r"\b\w+\b", question.lower())
    keywords = [word for word in words if word not in COMMON_STOPWORDS and len(word) > 2]
    return keywords


def format_meetings_for_prompt(meetings):
    if not meetings:
        return "No relevant meetings found."

    formatted = []

    for i, meeting in enumerate(meetings[:5], start=1):
        transcript = meeting.get("transcript", "")
        if len(transcript) > _TRANSCRIPT_LIMIT:
            transcript = transcript[:_TRANSCRIPT_LIMIT] + "... [truncated]"

        formatted.append(
            f"""
Meeting {i}
Source File: {meeting.get('_source_file', 'Unknown')}
Meeting Title: {meeting.get('meeting_title', '')}
Meeting Date: {meeting.get('meeting_date', '')}
Meeting Timestamp: {meeting.get('meeting_timestamp', '')}
Participants: {meeting.get('participants', [])}
Meeting Summary: {meeting.get('meeting_summary', '')}
Key Decisions: {meeting.get('key_decisions', [])}
Action Items: {meeting.get('action_items', [])}
Deadlines: {meeting.get('deadlines', [])}
Risks: {meeting.get('risks', [])}
Transcript: {transcript}
"""
        )

    return "\n".join(formatted)


def select_relevant_meetings(question: str, org_id: int):
    recent_meetings = get_recent_meetings(org_id, limit=10)
    question_lower = question.lower()

    # 1. Specific date query — highest priority
    target_date = extract_date_from_question(question)
    if target_date:
        date_matches = search_meetings_by_date(target_date, recent_meetings)
        if date_matches:
            return date_matches[:5]

    # 2. Relative recency
    if any(phrase in question_lower for phrase in ["last meeting", "latest meeting", "previous meeting"]):
        return recent_meetings[:1]

    # 3. Person name
    person = extract_possible_person(question)
    if person:
        person_matches = search_meetings_by_person(person, recent_meetings)
        if person_matches:
            return person_matches[:5]

    # 4. Keywords
    keywords = extract_keywords(question)
    if keywords:
        keyword_matches = search_meetings_by_keywords(keywords, recent_meetings)
        if keyword_matches:
            return keyword_matches[:5]

    return recent_meetings[:5]


async def ask_meetings(question: str, org_id: int):
    relevant_meetings = select_relevant_meetings(question, org_id)
    meeting_context = format_meetings_for_prompt(relevant_meetings)

    provider = get_llm_provider()

    prompt = f"""
You are an AI meeting assistant.

Answer the user's question using only the relevant meeting data below.
Prefer concise, clear answers.
If the answer is not clearly found in the meetings, say that you could not find it.

Relevant Meetings:
{meeting_context}

User Question:
{question}
"""

    answer = await provider.generate(prompt)

    return {
        "question": question,
        "matched_meetings_count": len(relevant_meetings),
        "answer": answer
    }
