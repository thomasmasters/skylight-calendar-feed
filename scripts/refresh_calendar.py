#!/usr/bin/env python3
"""Build the public Skylight feed from a private Outlook ICS URL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
DEFAULT_CATEGORIES = ("Personal", "Other", "Orange Category")


@dataclass
class Property:
    name: str
    params: dict[str, str]
    value: str


@dataclass
class Event:
    source_uid: str
    dtstart: Property
    dtend: Property
    summary: str
    categories: tuple[str, ...]
    description: str | None = None
    uid: str | None = None
    dtstamp: str | None = None


def unfold(text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    unfolded: list[str] = []
    for line in lines:
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def parse_property(line: str) -> Property | None:
    if ":" not in line:
        return None
    left, value = line.split(":", 1)
    parts = left.split(";")
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            key, param_value = part.split("=", 1)
            params[key.upper()] = param_value.strip('"')
    return Property(parts[0].upper(), params, value)


def event_blocks(text: str) -> Iterable[list[Property]]:
    current: list[Property] | None = None
    for line in unfold(text):
        marker = line.upper()
        if marker == "BEGIN:VEVENT":
            current = []
        elif marker == "END:VEVENT" and current is not None:
            yield current
            current = None
        elif current is not None:
            prop = parse_property(line)
            if prop:
                current.append(prop)


def read_text_preserving_newlines(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


def first(properties: list[Property], name: str) -> Property | None:
    return next((item for item in properties if item.name == name), None)


def split_categories(value: str) -> tuple[str, ...]:
    # Outlook categories do not normally contain escaped commas; handle them anyway.
    result: list[str] = []
    token: list[str] = []
    escaped = False
    for char in value:
        if escaped:
            token.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ",":
            result.append("".join(token).strip())
            token = []
        else:
            token.append(char)
    result.append("".join(token).strip())
    return tuple(item for item in result if item)


def windows_tz(tzid: str) -> ZoneInfo:
    aliases = {
        "GMT Standard Time": "Europe/London",
        "UTC": "UTC",
        "Etc/UTC": "UTC",
    }
    return ZoneInfo(aliases.get(tzid, tzid))


def parse_temporal(prop: Property) -> date | datetime:
    value = prop.value.strip()
    if prop.params.get("VALUE", "").upper() == "DATE" or len(value) == 8:
        return datetime.strptime(value[:8], "%Y%m%d").date()

    is_utc = value.endswith("Z")
    clean = value[:-1] if is_utc else value
    pattern = "%Y%m%dT%H%M%S" if len(clean) >= 15 else "%Y%m%dT%H%M"
    parsed = datetime.strptime(clean[:15] if pattern.endswith("%S") else clean[:13], pattern)
    if is_utc:
        return parsed.replace(tzinfo=timezone.utc)
    tzid = prop.params.get("TZID")
    return parsed.replace(tzinfo=windows_tz(tzid) if tzid else LONDON)


def london_property(name: str, prop: Property) -> Property:
    value = parse_temporal(prop)
    if isinstance(value, datetime):
        local = value.astimezone(LONDON)
        return Property(name, {"TZID": "Europe/London"}, local.strftime("%Y%m%dT%H%M%S"))
    return Property(name, {"VALUE": "DATE"}, value.strftime("%Y%m%d"))


def parse_events(text: str, allowed_categories: tuple[str, ...]) -> list[Event]:
    allowed = {item.casefold(): item for item in allowed_categories}
    events: list[Event] = []
    for properties in event_blocks(text):
        uid = first(properties, "UID")
        start = first(properties, "DTSTART")
        end = first(properties, "DTEND")
        summary = first(properties, "SUMMARY")
        categories_prop = first(properties, "CATEGORIES")
        if not all((uid, start, summary, categories_prop)):
            continue
        categories = split_categories(categories_prop.value)
        selected = tuple(allowed[item.casefold()] for item in categories if item.casefold() in allowed)
        if not selected:
            continue

        local_start = london_property("DTSTART", start)
        if end:
            # RFC 5545 all-day DTEND is already exclusive. Preserving it is the
            # essential multi-day fix: never replace it with DTSTART + one day.
            local_end = london_property("DTEND", end)
        else:
            parsed_start = parse_temporal(start)
            if isinstance(parsed_start, datetime):
                fallback = parsed_start + timedelta(hours=1)
                local_end = Property("DTEND", {"TZID": "Europe/London"}, fallback.astimezone(LONDON).strftime("%Y%m%dT%H%M%S"))
            else:
                local_end = Property("DTEND", {"VALUE": "DATE"}, (parsed_start + timedelta(days=1)).strftime("%Y%m%d"))
        description = first(properties, "DESCRIPTION")
        stamp = first(properties, "DTSTAMP")
        events.append(Event(
            source_uid=uid.value,
            dtstart=local_start,
            dtend=local_end,
            summary=summary.value,
            categories=selected,
            description=description.value if description else None,
            dtstamp=stamp.value if stamp else None,
        ))
    return events


def property_line(prop: Property) -> str:
    params = "".join(f";{key}={value}" for key, value in prop.params.items())
    return f"{prop.name}{params}:{prop.value}"


def fingerprint(event: Event) -> str:
    data = {
        "start": property_line(event.dtstart),
        "end": property_line(event.dtend),
        "summary": event.summary,
        "categories": event.categories,
        "description": event.description,
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def existing_metadata(path: Path) -> dict[str, tuple[str, str]]:
    if not path.exists():
        return {}
    result: dict[str, tuple[str, str]] = {}
    for properties in event_blocks(read_text_preserving_newlines(path)):
        uid = first(properties, "UID")
        stamp = first(properties, "DTSTAMP")
        start = first(properties, "DTSTART")
        end = first(properties, "DTEND")
        summary = first(properties, "SUMMARY")
        categories = first(properties, "CATEGORIES")
        description = first(properties, "DESCRIPTION")
        if all((uid, stamp, start, end, summary, categories)):
            event = Event(
                source_uid=uid.value,
                uid=uid.value,
                dtstamp=stamp.value,
                dtstart=start,
                dtend=end,
                summary=summary.value,
                categories=split_categories(categories.value),
                description=description.value if description else None,
            )
            result[fingerprint(event)] = (uid.value, stamp.value)
    return result


def load_uid_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(key): str(value) for key, value in data.items()}


def source_key(source_uid: str) -> str:
    return hashlib.sha256(source_uid.encode()).hexdigest()


def assign_identity(events: list[Event], existing: dict[str, tuple[str, str]], uid_map: dict[str, str]) -> None:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for event in events:
        key = source_key(event.source_uid)
        same_event = existing.get(fingerprint(event))
        if key in uid_map:
            event.uid = uid_map[key]
        elif same_event:
            event.uid = same_event[0]
            uid_map[key] = event.uid
        else:
            event.uid = f"{key[:8]}@skylight-calendar-feed"
            uid_map[key] = event.uid
        event.dtstamp = same_event[1] if same_event else normalise_stamp(event.dtstamp) or now


def normalise_stamp(value: str | None) -> str | None:
    if not value:
        return None
    try:
        clean = value.rstrip("Z")
        parsed = datetime.strptime(clean[:15], "%Y%m%dT%H%M%S")
        return parsed.strftime("%Y%m%dT%H%M%SZ")
    except ValueError:
        return None


def fold(line: str, limit: int = 75) -> list[str]:
    chunks: list[str] = []
    remaining = line
    first_line = True
    while remaining:
        available = limit if first_line else limit - 1
        used = 0
        cut = 0
        for index, char in enumerate(remaining):
            size = len(char.encode("utf-8"))
            if used + size > available:
                break
            used += size
            cut = index + 1
        if cut == 0:
            cut = 1
        chunks.append(("" if first_line else " ") + remaining[:cut])
        remaining = remaining[cut:]
        first_line = False
    return chunks or [""]


def render(events: list[Event]) -> str:
    header = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Tom Masters//Filtered Outlook Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Skylight Calendar",
    ]
    lines = list(header)
    for event in sorted(events, key=lambda item: (item.dtstart.value, item.summary.casefold())):
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{event.uid}",
            f"DTSTAMP:{event.dtstamp}",
            property_line(event.dtstart),
            property_line(event.dtend),
            f"SUMMARY:{event.summary}",
            f"CATEGORIES:{','.join(event.categories)}",
        ])
        if event.description:
            lines.append(f"DESCRIPTION:{event.description}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in fold(line)) + "\r\n"


def validate(text: str) -> int:
    if not text.startswith("BEGIN:VCALENDAR\r\n") or not text.endswith("END:VCALENDAR\r\n"):
        raise ValueError("output is not a complete VCALENDAR")
    if "\r\nLOCATION" in text:
        raise ValueError("LOCATION unexpectedly present in public output")
    starts = text.count("BEGIN:VEVENT\r\n")
    ends = text.count("END:VEVENT\r\n")
    if starts != ends:
        raise ValueError("VEVENT markers are unbalanced")
    return starts


def fetch(url: str) -> str:
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    request = urllib.request.Request(url, headers={"User-Agent": "skylight-calendar-feed/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(10_000_001)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"calendar download failed ({type(exc).__name__})") from None
    if len(data) > 10_000_000:
        raise RuntimeError("calendar download exceeded 10 MB")
    return data.decode("utf-8-sig")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/filtered-calendar.ics"))
    parser.add_argument("--uid-map", type=Path, default=Path("data/uid-map.json"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if args.check:
        count = validate(read_text_preserving_newlines(args.output))
        print(f"Calendar valid: {count} events")
        return 0

    source_url = os.environ.get("OUTLOOK_ICS_URL")
    if not source_url:
        print("OUTLOOK_ICS_URL is not configured", file=sys.stderr)
        return 2
    allowed = tuple(item.strip() for item in os.environ.get("ALLOWED_CATEGORIES", ",".join(DEFAULT_CATEGORIES)).split(",") if item.strip())
    current_count = 0
    existing = existing_metadata(args.output)
    if args.output.exists():
        current_count = sum(1 for _ in event_blocks(read_text_preserving_newlines(args.output)))

    events = parse_events(fetch(source_url), allowed)
    if not events:
        raise RuntimeError("refusing to publish an empty calendar")
    if current_count >= 10 and len(events) < current_count / 2 and os.environ.get("ALLOW_LARGE_DROP") != "1":
        raise RuntimeError(f"refusing unusually large event-count drop ({current_count} to {len(events)})")

    uid_map = load_uid_map(args.uid_map)
    assign_identity(events, existing, uid_map)
    output = render(events)
    validate(output)
    atomic_write(args.output, output)
    atomic_write(args.uid_map, json.dumps(dict(sorted(uid_map.items())), indent=2) + "\n")
    print(f"Calendar refreshed: {len(events)} events")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Refresh failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
