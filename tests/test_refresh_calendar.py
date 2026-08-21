import unittest

from refresh_calendar import remove_properties


class RemovePropertiesTests(unittest.TestCase):
    def test_removes_location_and_folded_continuations(self):
        source = (
            b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:Trip\r\n"
            b"LOCATION;LANGUAGE=en-GB:Long place name\r\n continued\r\n"
            b"DESCRIPTION:Keep this\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        result = remove_properties(source, {b"LOCATION"})
        self.assertNotIn(b"LOCATION", result)
        self.assertNotIn(b" continued", result)
        self.assertIn(b"DESCRIPTION:Keep this", result)
        self.assertTrue(result.endswith(b"\r\n"))


if __name__ == "__main__":
    unittest.main()

