import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts import make_short  # noqa: E402


class GlitchTests(unittest.TestCase):
    def test_bursts_are_irregular_not_a_metronome(self):
        hits = [n for n in range(200) if make_short.glitch_burst(n)]
        gaps = {b - a for a, b in zip(hits, hits[1:])}
        self.assertGreater(len(gaps), 3)
        self.assertTrue(0.1 < len(hits) / 200 < 0.35)

    def test_a_burst_stays_inside_the_frame(self):
        for n in range(300):
            g = make_short.glitch_burst(n)
            if g:
                self.assertLessEqual(g["x"] + 2 * g["w"], 1.0)
                self.assertLessEqual(g["y"] + g["h"], 1.0)

    def test_the_filter_splits_colour_tears_a_band_and_adds_grain(self):
        chain = make_short.effect_filter("glitch", 1080, 1920, 3.0)
        for part in ("rgbashift", "swaprect", "noise"):
            self.assertIn(part, chain)

    def test_a_burst_frame_differs_from_a_clean_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = str(Path(tmp) / "s.mp4"), str(Path(tmp) / "g.mp4")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x568:rate=30:duration=3",
                            "-f", "lavfi", "-i", "sine=duration=3", "-shortest", "-pix_fmt", "yuv420p", src], check=True)
            plain = str(Path(tmp) / "p.mp4")
            make_short.build_montage(src, [(0, 3, None)], 0, out, [{**make_short.DEFAULT_OPTIONS, "effect": "glitch"}])
            make_short.build_montage(src, [(0, 3, None)], 0, plain)
            n = next(n for n in range(5, 36) if make_short.glitch_burst(n))
            t = f"{n * make_short.GLITCH_SLOT + 0.04:.3f}"

            def frame(path):
                return subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", t, "-i", path, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                      capture_output=True, check=True).stdout

            self.assertNotEqual(frame(out), frame(plain))


if __name__ == "__main__":
    unittest.main()
