import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import clipper


class SectionArgs(unittest.TestCase):
    def test_range_and_tag(self):
        flags, tag = clipper.section_args(12.5, 40)
        self.assertEqual(flags[:2], ["--download-sections", "*12.50-40.00"])
        self.assertEqual(tag, "-12-40")


class LiveName(unittest.TestCase):
    def test_title_and_start_time(self):
        import time
        started = time.mktime((2026, 10, 16, 19, 4, 25, 0, 0, -1))
        self.assertEqual(clipper.live_tag("LIVE | Clock - EST (Current time)", started), "LIVE_Clock_EST_Current_time-190425")

    def test_no_title(self):
        self.assertTrue(clipper.live_tag("", 0).startswith("stream-"))

    def test_free_path_avoids_a_clash(self, ):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.mp4").write_text("x")
            self.assertEqual(clipper.free_path(Path(tmp), "a", ".mp4").name, "a-2.mp4")


class LiveWindow(unittest.TestCase):
    def test_counts_back_from_the_live_edge(self):
        offset, length = clipper.live_window(3600, 600, 590)
        self.assertEqual((offset, length), (3000, 10))

    def test_left_the_buffer(self):
        with self.assertRaises(ValueError):
            clipper.live_window(3600, 3700, 3690)

    def test_out_before_in(self):
        with self.assertRaises(ValueError):
            clipper.live_window(3600, 100, 120)

    def test_playlist_length(self):
        self.assertAlmostEqual(clipper.playlist_length("#EXTINF:5.005,\nu\n#EXTINF:4.5,\nu\n"), 9.505)


if __name__ == "__main__":
    unittest.main()
