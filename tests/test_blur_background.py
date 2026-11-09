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

    def frame_detail(self, video, at, rows):
        """How much fine detail (the mean step in brightness from one pixel to the next) the given rows of the frame at `at` seconds hold:
        a sharp picture has plenty, a blur has almost none."""
        top, bottom = rows
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(video), "-frames:v", "1",
                              "-vf", f"crop=iw:ih*{bottom - top}:0:ih*{top},scale=540:24:flags=neighbor,format=gray", "-f", "rawvideo", "-"],
                             capture_output=True, check=True).stdout
        steps = [abs(raw[row * 540 + x + 1] - raw[row * 540 + x]) for row in range(24) for x in range(539)]
        return sum(steps) / len(steps)

    def test_a_filled_clip_zoomed_out_is_not_cropped_to_the_sources_own_window(self):
        # Zoom 0.5 of a 640x480 clip in a 1080x1920 box is a picture 1080 wide and 960 tall: rows .25 to .75 of the frame.
        # The render used to crop it to a 4:3 window (rows .29 to .71) and blur the rest, so the zoom never showed as set.
        noisy = self.dir / "noisy.mp4"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=640x480:r=30:d=3,noise=alls=90:allf=t+u",
                        "-f", "lavfi", "-i", "sine=d=3", "-shortest", "-pix_fmt", "yuv420p", "-crf", "10", str(noisy)], check=True)
        (self.dir / "zoom.cuts").write_text(f"@zoom 0.5\n{noisy} | 0 - 2\n")
        out = self.dir / "fill.mp4"
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_short.py"), "--cuts", str(self.dir / "zoom.cuts"), "--card", "--layout", "title",
                        "--text=", "--template", "fill", "--blur-bg", "--out", str(out)], check=True, capture_output=True)
        self.assertGreater(self.frame_detail(out, 1, (0.26, 0.285)), 5, "the picture reaches the top of its zoomed size")
        self.assertGreater(self.frame_detail(out, 1, (0.715, 0.74)), 5, "and the bottom")
        self.assertLess(self.frame_detail(out, 1, (0.02, 0.2)), 2, "above it is the soft copy, not black or a second picture")


if __name__ == "__main__":
    unittest.main()
