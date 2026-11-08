import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import clip_motion  # noqa: E402
import clipper  # noqa: E402
import video_scan  # noqa: E402


def make(tmp, name="v.mp4"):
    path = Path(tmp) / name
    # a still gray stretch, then a hard cut to moving test pattern
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:size=320x180:rate=25:d=3",
                    "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:d=3",
                    "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p", str(path)], check=True)
    return str(path)


class CutTimes(unittest.TestCase):
    def test_keeps_cuts_at_least_min_gap_apart(self):
        log = "pts_time:1.0 x\npts_time:1.2 x\npts_time:2.0 x"
        self.assertEqual(video_scan.cut_times(log, 0.5), [1.0, 2.0])

    def test_no_cuts_is_an_empty_list(self):
        self.assertEqual(video_scan.cut_times("nothing here", 0.5), [])


class Scan(unittest.TestCase):
    def test_one_decode_matches_the_two_separate_scans(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = make(tmp)
            scenes, motion = video_scan.scan(src, clipper.SCENE_THRESHOLD, clipper.SCENE_MIN_GAP)
            self.assertEqual(scenes, clipper.detect_scenes(src))
            self.assertEqual(motion, clip_motion.compute(src))
        self.assertTrue(scenes)

    def test_an_unreadable_file_gives_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.mp4"
            bad.write_bytes(b"not a video")
            self.assertEqual(video_scan.scan(bad, 0.3, 0.5), (None, None))


class SceneJobSavesMotion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vid = "a" * 12
        self.src = make(self.tmp.name)
        for target, value in (("PROXY_DIR", Path(self.tmp.name) / "proxy"),):
            patcher = mock.patch.object(clipper, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        clipper.registry[self.vid] = self.src
        self.addCleanup(clipper.registry.pop, self.vid, None)
        self.addCleanup(clipper.scene_jobs.pop, self.vid, None)

    def test_scanning_for_cuts_also_saves_the_motion(self):
        clipper.scene_jobs[self.vid] = {"state": "working"}
        clipper.run_scenes(self.vid)
        self.assertEqual(clipper.scene_jobs[self.vid]["state"], "ready")
        saved = json.loads(clipper.motion_path(self.vid).read_text())
        self.assertEqual(saved, clip_motion.compute(self.src))
        with mock.patch.object(clip_motion, "compute", side_effect=AssertionError("decoded again")):
            self.assertEqual(clipper.load_motion(self.vid, self.src), saved)


if __name__ == "__main__":
    unittest.main()
