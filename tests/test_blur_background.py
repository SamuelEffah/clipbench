import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is needed")
class BlurBackgroundTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.src = self.dir / "src.mp4"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=d=3:s=640x480:r=30",
                        "-f", "lavfi", "-i", "sine=d=3", "-shortest", "-pix_fmt", "yuv420p", str(self.src)], check=True)
        (self.dir / "one.cuts").write_text(f"{self.src} | 0 - 2\n")

    def render(self, *extra):
        out = self.dir / "out.mp4"
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_short.py"), str(self.src), "--cuts", str(self.dir / "one.cuts"),
                        "--card", "--layout", "title", "--text", "hook", "--out", str(out), *extra],
                       check=True, capture_output=True)
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=width,height,sample_aspect_ratio", "-of", "csv=p=0", str(out)],
                               capture_output=True, text=True, check=True).stdout.strip()
        return probe.split(",")

    def test_blurred_background_keeps_square_pixels(self):
        # A backdrop scaled from 4:3 to 9:16 would otherwise carry a 64:27 pixel aspect and play back stretched.
        width, height, sar = self.render("--blur-bg")
        self.assertEqual((width, height), ("1080", "1920"))
        self.assertIn(sar, ("1:1", "N/A"))


if __name__ == "__main__":
    unittest.main()
