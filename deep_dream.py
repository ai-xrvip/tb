"""
Deep Dream — Nightly conversation summarization.
Runs once per day, summarizes each user's conversations into long-term memory.
"""
from database import db
from utils.logger import logger

SUMMARY_PROMPT = """You are a memory summarizer. Below is today's conversation between a user and their AI girlfriend character.

Summarize the key facts in 3-5 bullet points:
- What the user talked about today
- Any personal info the user shared (name, job, hobbies, mood, plans)
- Any emotional moments or important events
- What the user seems to want or need

Keep it short. Write in Chinese. Just the bullet points, no introduction."""

MIN_MSGS_FOR_SUMMARY = 10


async def summarize_user_conversation(user_id: int, role_id: str):
    """Summarize a user's recent conversation with a role, returns summary or None"""
    history = db.get_chat_history(user_id)
    if not history or len(history) < MIN_MSGS_FOR_SUMMARY:
        return None

    recent = history[-30:]
    conv_lines = []
    for m in recent:
        role_label = "user" if m["role"] == "user" else "AI"
        content = str(m.get("content", ""))[:200]
        conv_lines.append(role_label + ": " + content)
    conv_text = "\n".join(conv_lines)

    if len(conv_text) < 100:
        return None

    try:
        from providers.factory import get_provider_from_config
        provider = get_provider_from_config()

        summary = await provider.chat(
            messages=[
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": "Today's conversation:\n\n" + conv_text},
            ],
            max_tokens=300,
            temperature=0.3,
        )

        if summary and len(summary) > 10:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            db.conn.execute(
                "INSERT INTO chat_summaries (user_id, summary_text, msg_count, created_at) VALUES (?, ?, ?, ?)",
                (user_id, summary, len(recent), now),
            )
            db.conn.commit()
            logger.info("Deep Dream summary for user=" + str(user_id) + ": " + summary[:100])
            return summary

    except Exception as e:
        logger.debug("Deep Dream failed for user=" + str(user_id) + ": " + str(e))

    return None


def get_recent_summaries(user_id: int, role_id: str, days: int = 7):
    """Get summaries from the last N days for context injection"""
    rows = db.conn.execute(
        "SELECT summary_text FROM chat_summaries WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (user_id, days),
    ).fetchall()
    return [r["summary_text"] for r in rows]


def get_summary_context(user_id: int, role_id: str, max_summaries: int = 7):
    """Get summary context for injection into system prompt"""
    summaries = get_recent_summaries(user_id, role_id, max_summaries)
    if not summaries:
        return ""

    lines = ["[Here are your recent conversation summaries. Weave them naturally into the chat, do not recite verbatim.]"]
    for i, s in enumerate(summaries, 1):
        lines.append("Day " + str(i) + ": " + s)

    return "\n".join(lines)
