"""Shared clock / relative-time helpers for persona prompts and memory aging."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def now_local() -> datetime:
    return datetime.now().astimezone()


def now_local_iso() -> str:
    """Local ISO-8601 with offset (e.g. 2026-07-27T18:24:00-04:00)."""
    return now_local().replace(microsecond=0).isoformat()


def parse_timestamp(value: Any) -> datetime | None:
    """Parse SQLite / ISO timestamps. Naive values are treated as UTC (SQLite default)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    text = str(value).strip()
    if not text:
        return None
    # SQLite CURRENT_TIMESTAMP: "YYYY-MM-DD HH:MM:SS"
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(str(value).strip(), fmt)
                break
            except ValueError:
                dt = None
        if dt is None:
            return None
    if dt.tzinfo is None:
        # Legacy SQLite defaults are UTC; new rows use local ISO with offset.
        return dt.replace(tzinfo=timezone.utc)
    return dt


def format_clock(when: datetime | None = None) -> str:
    # Manual hour strip: %-I is POSIX-only; %#I is Windows-only.
    dt = (when or now_local()).astimezone()
    hour = dt.strftime("%I").lstrip("0") or "0"
    zone = dt.tzname() or ""
    stamp = dt.strftime(f"%A, %B %d, %Y · {hour}:%M %p")
    if zone:
        stamp = f"{stamp} {zone}"
    return stamp

def format_chat_stamp(when: datetime | None, *, now: datetime | None = None) -> str:
    """Compact stamp for history lines, e.g. Jul 27 6:24 PM."""
    if when is None:
        return ""
    local = when.astimezone()
    ref = (now or now_local()).astimezone()
    hour = local.strftime("%I").lstrip("0") or "0"
    time_part = local.strftime(f"{hour}:%M %p")
    if local.date() == ref.date():
        return time_part
    if local.year == ref.year:
        return local.strftime(f"%b %d {time_part}")
    return local.strftime(f"%b %d %Y {time_part}")


def humanize_delta(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 45:
        return "just now"
    if seconds < 90:
        return "about a minute ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = delta.days
    if days < 14:
        return f"{days} day{'s' if days != 1 else ''} ago"
    weeks = days // 7
    if weeks < 8:
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    months = days // 30
    if months < 24:
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = days // 365
    return f"{years} year{'s' if years != 1 else ''} ago"


def relative_age(
    created_at: Any,
    *,
    now: datetime | None = None,
) -> str:
    dt = parse_timestamp(created_at)
    if dt is None:
        return ""
    ref = now or now_local()
    return humanize_delta(ref - dt)


def gap_guidance(delta: timedelta | None, *, first_chat: bool) -> str:
    if first_chat:
        return (
            "This is the first message on record for this persona. "
            "Meet them naturally — do not pretend you already shared a long history."
        )
    if delta is None:
        return "Respond in the present moment; keep continuity with recent context."
    seconds = delta.total_seconds()
    if seconds < 10 * 60:
        return (
            "Conversation is continuous. Pick up mid-thread; "
            "do not re-greet or re-introduce yourself."
        )
    if seconds < 6 * 3600:
        return (
            "Same day, but there was a short break. Soft acknowledgment is fine; "
            "do not restart from zero."
        )
    if seconds < 36 * 3600:
        return (
            "It has been a while since the last message (hours). "
            "A light time-aware greeting is okay if it fits; then answer THIS message."
        )
    if seconds < 7 * 24 * 3600:
        return (
            "Days have passed since the last chat. Acknowledge the gap briefly if natural, "
            "then focus on what they said now — do not dump an old session recap."
        )
    return (
        "A long time has passed since the last chat. Notice the gap warmly once if it fits, "
        "then answer THIS message. Do not pretend you were together the whole time."
    )


def build_temporal_context_block(
    *,
    last_user_at: Any = None,
    now: datetime | None = None,
) -> str:
    """System-prompt block: clock + gap since last user turn."""
    ref = now or now_local()
    lines = [
        "[TEMPORAL CONTEXT]",
        f"- Local time now: {format_clock(ref)}",
    ]
    last_dt = parse_timestamp(last_user_at)
    if last_dt is None:
        lines.append("- Last user message: (none on record — first chat)")
        lines.append(f"- Guidance: {gap_guidance(None, first_chat=True)}")
    else:
        delta = ref - last_dt
        lines.append(
            f"- Last user message: {format_clock(last_dt)} "
            f"({humanize_delta(delta)})"
        )
        lines.append(f"- Guidance: {gap_guidance(delta, first_chat=False)}")
    lines.append(
        "- Use time naturally when it matters (greetings, plans, 'earlier today'). "
        "Do not announce the clock every turn."
    )
    return "\n".join(lines)


def stamp_message_content(
    content: str,
    created_at: Any,
    *,
    now: datetime | None = None,
) -> str:
    stamp = format_chat_stamp(parse_timestamp(created_at), now=now)
    text = content or ""
    if not stamp:
        return text
    return f"[{stamp}] {text}"
