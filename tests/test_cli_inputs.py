import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import make_short  # noqa: E402


class InlineCuts(unittest.TestCase):
    def test_a_long_inline_list_is_read_as_text(self):
        text = "\n".join(f"{n}:00 - {n}:05" for n in range(1, 200))
        self.assertEqual(len(make_short.read_cuts(text)), 199)


class SubtitleTiming(unittest.TestCase):
    def test_cues_follow_the_overlap_of_a_transition(self):
        cues = [(10.5, 11.5, "a"), (20.5, 21.5, "b")]
        out = make_short.remap_cues(cues, [(10, 14), (20, 24)], [0.0, 0.5])
        self.assertEqual(out, [(0.5, 1.5, "a"), (4.0, 5.0, "b")])

    def test_without_overlaps_ranges_join_end_to_end(self):
        out = make_short.remap_cues([(20.5, 21.5, "b")], [(10, 14), (20, 24)])
        self.assertEqual(out, [(4.5, 5.5, "b")])


class SrtFiles(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.srt"
            path.write_text(text)
            return make_short.load_cues(str(path), "clip.mp4", tmp)

    def test_cues_without_numbers_are_read(self):
        cues = self.load("00:00:01,000 --> 00:00:02,000\nhello\n\n00:00:03,000 --> 00:00:04,500\nthere\n")
        self.assertEqual(cues, [(1.0, 2.0, "hello"), (3.0, 4.5, "there")])

    def test_position_after_the_end_time_is_ignored(self):
        cues = self.load("1\n00:00:01,000 --> 00:00:02,000 X1:10 X2:20 Y1:5 Y2:9\nhello\n")
        self.assertEqual(cues, [(1.0, 2.0, "hello")])


if __name__ == "__main__":
    unittest.main()
