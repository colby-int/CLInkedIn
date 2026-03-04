import re
from typing import Iterable

UNKNOWN_AGE_MINUTES = 10**9

_UNIT_TO_MINUTES = {
    "minute": 1,
    "hour": 60,
    "day": 24 * 60,
    "week": 7 * 24 * 60,
    "month": 30 * 24 * 60,
}

_RELATIVE_DATE_PATTERN = re.compile(
    r"(?P<value>\d+)\s+(?P<unit>minute|hour|day|week|month)s?\s+ago", re.IGNORECASE
)


def posted_date_to_minutes(posted_date: str | None) -> int:
    if not posted_date:
        return UNKNOWN_AGE_MINUTES

    normalized = posted_date.strip().lower()
    if not normalized or normalized == "n/a":
        return UNKNOWN_AGE_MINUTES

    if normalized in {"today", "just now"}:
        return 0

    # LinkedIn sometimes prefixes this text, e.g. "Reposted 2 days ago".
    normalized = normalized.replace("reposted", "").strip()

    match = _RELATIVE_DATE_PATTERN.search(normalized)
    if not match:
        return UNKNOWN_AGE_MINUTES

    value = int(match.group("value"))
    unit = match.group("unit")
    return value * _UNIT_TO_MINUTES[unit]


def sort_jobs_by_date(jobs: Iterable[dict]) -> list[dict]:
    return sorted(
        jobs,
        key=lambda job: (
            posted_date_to_minutes(str(job.get("posted_date", ""))),
            str(job.get("title", "")).lower(),
        ),
    )
