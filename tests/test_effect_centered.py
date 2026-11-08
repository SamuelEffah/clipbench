import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts import make_short  # noqa: E402

W, H, LENGTH = 320, 180, 2.0


def last_frame_rows(effect, tmp):
    """The colour of each row of the final frame of a clip with a red top band and a blue bottom band, as (red rows, blue rows)."""
    src = Path(tmp) / "bands.png"
    out = Path(tmp) / "out.rgb"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=gray:s={W}x{H}",
                    "-vf", f"drawbox=x=0:y=0:w={W}:h=30:color=red:t=fill,drawbox=x=0:y={H - 30}:w={W}:h=30:color=blue:t=fill",
                    "-frames:v", "1", str(src)], check=True)
    graph = f"[0:v]fps=30{make_short.effect_filter(effect, W, H, LENGTH)},trim=start={LENGTH - 0.1},format=rgb24"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", "30", "-t", str(LENGTH), "-i", str(src),
                    "-filter_complex", graph, "-frames:v", "1", "-f", "rawvideo", str(out)], check=True)
    data = out.read_bytes()
    rows = [data[y * W * 3: y * W * 3 + 3] for y in range(H)]
    red = sum(1 for r in rows if r[0] > 200 and r[2] < 80)
    blue = sum(1 for r in rows if r[2] > 200 and r[0] < 80)
    return red, blue


class ZoomStaysCentred(unittest.TestCase):
    def test_zooming_in_trims_the_top_and_bottom_equally(self):
        for effect in ("zoom_in", "zoom_out", "punch"):
            with self.subTest(effect=effect), tempfile.TemporaryDirectory() as tmp:
                red, blue = last_frame_rows(effect, tmp)
                self.assertLessEqual(abs(red - blue), 2, f"{effect}: red rows {red}, blue rows {blue}")


if __name__ == "__main__":
    unittest.main()
