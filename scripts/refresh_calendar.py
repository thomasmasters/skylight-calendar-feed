"""Refresh a public iCalendar feed while removing event locations."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OUTPUT_PATH = Path(os.environ.get("OUTPUT_PATH", "docs/filtered-calendar.ics"))


def remove_properties(calendar: bytes, names: set[bytes]) -> bytes:
    """Remove named iCalendar properties and their folded continuation lines."""
    normalized = calendar.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    lines = normalized.split(b"\n")
    kept: list[bytes] = []
    dropping = False

    for line in lines:
        if line.startswith((b" ", b"\t")):
            if not dropping:
                kept.append(line)
            continue

        property_name = line.split(b":", 1)[0].split(b";", 1)[0].upper()
        dropping = property_name in names
        if not dropping:
            kept.append(line)

    result = b"\r\n".join(kept)
    if not result.endswith(b"\r\n"):
        result += b"\r\n"
    return result


def download_calendar(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "skylight-calendar-feed/1.0"})
    try:
        with urlopen(request, timeout=30) as response:
            return response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError("Unable to download the Outlook calendar feed") from exc


def main() -> None:
    source_url = os.environ.get("OUTLOOK_ICS_URL")
    if not source_url:
        raise SystemExit("OUTLOOK_ICS_URL is not configured")

    calendar = download_calendar(source_url)
    if b"BEGIN:VCALENDAR" not in calendar or b"END:VCALENDAR" not in calendar:
        raise SystemExit("Downloaded content is not a valid iCalendar feed")

    filtered = remove_properties(calendar, {b"LOCATION"})
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = OUTPUT_PATH.with_suffix(OUTPUT_PATH.suffix + ".tmp")
    temporary_path.write_bytes(filtered)
    temporary_path.replace(OUTPUT_PATH)


if __name__ == "__main__":
    main()

