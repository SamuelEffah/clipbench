import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts import clipper  # noqa: E402


class CaptionCarryTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.video = Path(self.dir.name) / "a.mp4"
        self.video.write_bytes(b"x")
        for name, value in (("PROJECT_DIR", Path(self.dir.name)), ("SHORT_DIR", Path(self.dir.name) / "shorts")):
            patch = mock.patch.object(clipper, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def captions(self, *clips):
        text, _ = clipper.export_cuts("cc", {"clips": [{"src": str(self.video), "in": 1, "out": 3, **c} for c in clips]})
        return [line for line in text.splitlines() if line.startswith("@caption")]

    def test_a_caption_carries_over_the_clips_without_one(self):
        self.assertEqual(self.captions({"caption": "hi"}, {}, {}), ["@caption hi"] * 3)

    def test_a_later_caption_takes_over(self):
        self.assertEqual(self.captions({"caption": "a"}, {}, {"caption": "b"}, {}), ["@caption a", "@caption a", "@caption b", "@caption b"])

    def test_capstop_ends_the_carry(self):
        self.assertEqual(self.captions({"caption": "a"}, {"capStop": True}, {}), ["@caption a"])

    def test_nothing_carries_from_a_timed_caption(self):
        timed = {"caption": "a", "capMode": "phrase", "words": [["a", 0, 0.5]]}
        self.assertEqual(self.captions(timed, {}), ["@caption a"])

    def text(self, *clips):
        text, _ = clipper.export_cuts("cc", {"clips": [{"src": str(self.video), "in": 1, "out": 3, **c} for c in clips]})
        return text

    def test_a_carried_clip_keeps_the_position_of_the_clip_it_carries_from(self):
        text = self.text({"caption": "a", "capX": 0.3, "capY": 0.4}, {"capX": 0.9, "capY": 0.9, "capLook": "box"})
        self.assertEqual(text.count("@capx"), 1)
        self.assertEqual(text.count("@caplook"), 0)

    def test_a_clip_with_its_own_caption_keeps_its_own_position(self):
        text = self.text({"caption": "a", "capX": 0.3, "capY": 0.4}, {"caption": "b", "capX": 0.9, "capY": 0.9})
        self.assertEqual(text.count("@capx"), 2)

    def test_the_bottom_lane_neither_gives_nor_takes(self):
        self.assertEqual(self.captions({"caption": "a"}, {"lane": "bottom"}), ["@caption a"])


if __name__ == "__main__":
    unittest.main()
