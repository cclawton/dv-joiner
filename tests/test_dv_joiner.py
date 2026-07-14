import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import dv_joiner


class TimestampTests(unittest.TestCase):
    def test_parses_semicolon_timestamp(self):
        self.assertEqual(
            dv_joiner.parse_datetime_from_filename("clip-2002-03-13 08;37;36.dv"),
            datetime(2002, 3, 13, 8, 37, 36),
        )

    def test_parses_compact_timestamp_without_seconds(self):
        self.assertEqual(
            dv_joiner.parse_datetime_from_filename("20020315_1430.dv"),
            datetime(2002, 3, 15, 14, 30),
        )


class EncodingCommandTests(unittest.TestCase):
    def _run(self, *, deinterlace: bool) -> list[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "clip.dv"
            source.write_bytes(b"dv")
            output = root / "joined.mp4"
            files = [{
                "path": source,
                "datetime": datetime(2002, 3, 13, 8, 37, 36),
                "filename": source.name,
                "size_mb": source.stat().st_size / (1024 * 1024),
            }]
            captured: list[str] = []

            def fake_run(command, **kwargs):
                captured.extend(command)
                output.write_bytes(b"mp4")
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("dv_joiner.subprocess.run", side_effect=fake_run):
                self.assertTrue(
                    dv_joiner.concatenate_dv_files(
                        files, output, deinterlace=deinterlace
                    )
                )
            return captured

    def test_deinterlace_filter_is_enabled_by_default(self):
        self.assertIn("yadif=mode=0", self._run(deinterlace=True))

    def test_deinterlace_filter_can_be_disabled(self):
        self.assertNotIn("yadif=mode=0", self._run(deinterlace=False))


if __name__ == "__main__":
    unittest.main()
