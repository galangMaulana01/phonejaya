from datetime import datetime, timezone


def fmt_waktu(dt: datetime) -> str:
    """Render as an unambiguous ISO-8601 UTC string (explicit +00:00 offset).

    Callers used to get a naive "YYYY-MM-DD HH:MM" string with no timezone
    marker, which every consumer had to *assume* was UTC. Emitting the
    offset lets clients convert to whichever local time they need (e.g. a
    branch's own timezone) instead of guessing.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()
