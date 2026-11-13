"""Opening-hours parsing for German Tankerkönig station data.

The API exposes machine-readable start/end times and a German weekday label.
This module interprets normal weekday patterns, multiple shifts, overnight
periods and exact dated overrides. It always marks any non-interpretable
exception instead of hiding it.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo

STATION_TZ = ZoneInfo("Europe/Berlin")
UTC = timezone.utc
DAYS = {
    "montag": 0, "mo": 0, "dienstag": 1, "di": 1, "mittwoch": 2, "mi": 2,
    "donnerstag": 3, "do": 3, "freitag": 4, "fr": 4,
    "samstag": 5, "sonnabend": 5, "sa": 5, "sonntag": 6, "so": 6,
}
DAY_PATTERN = "|".join(DAYS)
DAY_RULE = re.compile(rf"\b({DAY_PATTERN})\b\.?(?:\s*(?:-|bis)\s*({DAY_PATTERN})\b\.?)?", re.IGNORECASE)
OVERRIDE = re.compile(
    r"^\s*(\d{2}\.\d{2}\.\d{4},\s*\d{2}:\d{2}(?::\d{2})?)\s*-\s*"
    r"(\d{2}\.\d{2}\.\d{4},\s*\d{2}:\d{2}(?::\d{2})?)\s*:\s*"
    r"(geschlossen|geöffnet|closed|open)\s*$", re.IGNORECASE,
)


def parse_weekday_label(text: str) -> tuple[set[int] | None, bool]:
    """Return known weekdays and whether the complete label was understood.

    Tankerkönig frequently publishes compound labels such as
    ``Samstag, Sonntag, Feiertag``. Saturday and Sunday are still unambiguous
    normal weekly days, while ``Feiertag`` is an extra, non-weekly qualifier.
    Keeping the known days prevents their entities from incorrectly becoming
    ``unbekannt``; the second return value makes the partial interpretation
    explicit to the caller.
    """
    if not isinstance(text, str):
        return None, False
    text = text.casefold().strip().replace("–", "-").replace("—", "-")
    if text in ("täglich", "taeglich", "jeden tag", "daily"):
        return set(range(7)), True
    days = set()
    for match in DAY_RULE.finditer(text):
        first = DAYS[match[1].casefold()]
        last = DAYS[match[2].casefold()] if match[2] else first
        for offset in range((last - first) % 7 + 1):
            days.add((first + offset) % 7)
    # Colons/dots/brackets are harmless display punctuation. Any remaining
    # word (for example "Feiertag") is a qualifier we must not pretend to
    # have modelled as a recurring weekday.
    rest = DAY_RULE.sub("", text)
    # Some labels redundantly include a time that is also supplied by start/end.
    rest = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", "", rest)
    rest = re.sub(r"\bund\b|[\s,;:/&().\-]+", "", rest)
    return (days or None), not rest


def weekdays(text: str) -> set[int] | None:
    """Return weekday indices only when a label is fully understood.

    This strict public helper is retained for callers/tests that need to reject
    a holiday-qualified label. Rule parsing below deliberately retains known
    weekday portions through :func:`parse_weekday_label`.
    """
    days, complete = parse_weekday_label(text)
    return days if complete else None


def seconds(value: str) -> int:
    """Parse HH:MM[:SS], accepting 24:00 exactly as end of day."""
    parts = str(value).split(":")
    if len(parts) not in (2, 3):
        raise ValueError("Invalid time")
    hour, minute = int(parts[0]), int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    if hour == 24 and minute == second == 0:
        return 86400
    if not (0 <= hour < 24 and 0 <= minute < 60 and 0 <= second < 60):
        raise ValueError("Invalid time")
    return hour * 3600 + minute * 60 + second


def parse_regular_rules(details: dict) -> tuple[list[tuple[set[int], int, int]], bool]:
    """Read API rows as (weekdays, start seconds, end seconds), completeness."""
    rows = details.get("openingTimes") or []
    if not isinstance(rows, list):
        return [], False
    rules: list[tuple[set[int], int, int]] = []
    complete = True
    for row in rows:
        try:
            if not isinstance(row, dict):
                raise ValueError("Invalid rule")
            days, label_complete = parse_weekday_label(row["text"])
            begin, finish = seconds(row["start"]), seconds(row["end"])
            if days is None or begin >= 86400:
                raise ValueError("Unknown weekday rule")
            rules.append((days, begin, finish))
            complete = complete and label_complete
        except (KeyError, TypeError, ValueError, AttributeError):
            complete = False
    return rules, complete and bool(rules)


def merge_seconds(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge touching periods; a 12:00/12:00 shift change is not a closure."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def format_seconds(value: int) -> str:
    if value == 86400:
        return "24:00"
    return f"{value // 3600:02d}:{(value % 3600) // 60:02d}"


def weekday_periods(details: dict, weekday: int) -> tuple[list[tuple[int, int]], bool]:
    """Opening periods on exactly one local weekday, including overnight tails."""
    rules, complete = parse_regular_rules(details)
    periods: list[tuple[int, int]] = []
    previous_day = (weekday - 1) % 7
    for days, begin, finish in rules:
        if weekday in days:
            # An end before/equal start continues past midnight; show only the
            # part belonging to this calendar day.
            periods.append((begin, finish if finish > begin else 86400))
        if finish <= begin and previous_day in days:
            # The part after midnight belongs to this weekday.
            periods.append((0, finish))
    return merge_seconds(periods), complete


def weekday_summary(details: dict, weekday: int) -> tuple[str, list[dict[str, str]], bool]:
    """Return bounded HA state text, structured periods and parsing status."""
    periods, complete = weekday_periods(details, weekday)
    structured = [{"von": format_seconds(start), "bis": format_seconds(end)} for start, end in periods]
    if not periods:
        return ("geschlossen" if complete else "unbekannt"), structured, complete
    # Preserve known shifts even if another API row cannot be interpreted. The
    # attribute warns automations/UI code that this is only a partial schedule.
    result = ", ".join(f"{item['von']}–{item['bis']}" for item in structured)
    # Entity states are capped at 255 characters. The full representation is
    # still supplied as attributes if a station publishes unusually many rows.
    return (result if len(result) <= 255 else result[:252] + "…"), structured, complete


def merge(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def regular_intervals(details: dict, start: datetime, end: datetime):
    """Return regular UTC intervals overlapping a range and parse completeness."""
    rules, complete = parse_regular_rules(details)
    if not rules:
        return [], False
    first = start.astimezone(STATION_TZ).date() - timedelta(days=1)
    last = end.astimezone(STATION_TZ).date()
    intervals = []
    day = first
    while day <= last:
        midnight = datetime.combine(day, time(), tzinfo=STATION_TZ)
        for days, begin, finish in rules:
            if day.weekday() not in days:
                continue
            opening = midnight + timedelta(seconds=begin)
            closing = midnight + timedelta(seconds=finish + (86400 if finish <= begin else 0))
            opening, closing = opening.astimezone(UTC), closing.astimezone(UTC)
            if opening < end and closing > start:
                intervals.append((opening, closing))
        day += timedelta(days=1)
    return merge(intervals), complete


def parse_override(text: str):
    match = OVERRIDE.fullmatch(text) if isinstance(text, str) else None
    if not match:
        return None
    dates = []
    for value in (match[1], match[2]):
        value = re.sub(r",\s*", ", ", value)
        fmt = "%d.%m.%Y, %H:%M:%S" if value.count(":") == 2 else "%d.%m.%Y, %H:%M"
        try:
            dates.append(datetime.strptime(value, fmt).replace(tzinfo=STATION_TZ).astimezone(UTC))
        except ValueError:
            return None
    if dates[1] <= dates[0]:
        return None
    return dates[0], dates[1], match[3].casefold() in ("geöffnet", "open")


def forecast(details: dict, now: datetime):
    """Return next UTC boundary/action/reason without creating API requests.

    If an exception is free text we retain the normal weekly forecast but mark
    it prominently. This gives a usable normal-day timestamp instead of an
    unexplained unknown state while never claiming that the exception was read.
    """
    if details.get("wholeDay") is True:
        return None, None, "ganztags_geoeffnet"
    intervals, complete = regular_intervals(details, now - timedelta(days=1), now + timedelta(days=16))
    if not intervals:
        return None, None, "oeffnungszeiten_nicht_lesbar"
    partial_schedule = not complete
    overrides = details.get("overrides") or []
    if not isinstance(overrides, list):
        overrides = []
        unparsed_override = True
    else:
        unparsed_override = False
    for raw in overrides:
        override = parse_override(raw)
        if override is None:
            unparsed_override = True
            continue
        start, end, is_open = override
        result = []
        for left, right in intervals:
            if right <= start or left >= end:
                result.append((left, right))
            else:
                if left < start:
                    result.append((left, start))
                if right > end:
                    result.append((end, right))
        if is_open:
            result.append((start, end))
        intervals = merge(result)
    warning = (
        "oeffnungszeiten_teilweise_nicht_lesbar" if partial_schedule
        else "sonderoeffnungszeiten_nicht_ausgewertet" if unparsed_override
        else None
    )
    for start, end in intervals:
        if start <= now < end:
            if end <= now + timedelta(days=8):
                return end, "schließt", warning
            return None, None, "keine_aenderung_in_8_tagen"
        if start > now:
            if start <= now + timedelta(days=8):
                return start, "öffnet", warning
            break
    return None, None, "keine_aenderung_in_8_tagen"
