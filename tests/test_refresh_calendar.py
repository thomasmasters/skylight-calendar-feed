import tempfile
import unittest
from pathlib import Path

from scripts.refresh_calendar import (
    DEFAULT_CATEGORIES,
    assign_identity,
    existing_metadata,
    parse_events,
    render,
    validate,
)


SOURCE = """BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
UID:multi-day-source\r
DTSTAMP:20260825T070000Z\r
DTSTART;VALUE=DATE:20260904\r
DTEND;VALUE=DATE:20260907\r
SUMMARY:Bisbrooke\r
CATEGORIES:Personal\r
LOCATION:Private address\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:work-source\r
DTSTART:20260904T090000Z\r
DTEND:20260904T100000Z\r
SUMMARY:Confidential work meeting\r
CATEGORIES:Blue Category\r
END:VEVENT\r
END:VCALENDAR\r
"""


class RefreshCalendarTests(unittest.TestCase):
    def test_filters_category_strips_location_and_preserves_multi_day_end(self):
        events = parse_events(SOURCE, DEFAULT_CATEGORIES)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].dtend.value, "20260907")
        assign_identity(events, {}, {})
        output = render(events)
        self.assertNotIn("LOCATION", output)
        self.assertNotIn("Confidential", output)
        self.assertIn("DTEND;VALUE=DATE:20260907", output)
        self.assertEqual(validate(output), 1)

    def test_existing_uid_and_stamp_survive_first_automated_refresh(self):
        existing = """BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:c375efad@skylight-calendar-feed\r
DTSTAMP:20260821T103301Z\r
DTSTART;VALUE=DATE:20260904\r
DTEND;VALUE=DATE:20260907\r
SUMMARY:Bisbrooke\r
CATEGORIES:Personal\r
END:VEVENT\r
END:VCALENDAR\r
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calendar.ics"
            with path.open("w", encoding="utf-8", newline="") as handle:
                handle.write(existing)
            metadata = existing_metadata(path)
        events = parse_events(SOURCE, DEFAULT_CATEGORIES)
        uid_map = {}
        assign_identity(events, metadata, uid_map)
        self.assertEqual(events[0].uid, "c375efad@skylight-calendar-feed")
        self.assertEqual(events[0].dtstamp, "20260821T103301Z")
        self.assertEqual(len(uid_map), 1)


if __name__ == "__main__":
    unittest.main()
