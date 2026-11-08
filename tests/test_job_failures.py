import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import clipper  # noqa: E402


class BackgroundJobFailureTests(unittest.TestCase):
    """A job that can't run must end in an error, because the page polls for as long as it says it is working."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.video = root / "a.mp4"
        self.video.write_bytes(b"v")
        for name, value in (("PROXY_DIR", root / "proxy"), ("CUT_DIR", root / "cuts")):
            patch = mock.patch.object(clipper, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        clipper.registry["f" * 12] = self.video
        self.addCleanup(clipper.registry.pop, "f" * 12, None)
        broken = mock.patch.object(clipper.subprocess, "run", side_effect=OSError("no ffmpeg"))
        broken.start()
        self.addCleanup(broken.stop)
        popen = mock.patch.object(clipper.subprocess, "Popen", side_effect=OSError("no ffmpeg"))
        popen.start()
        self.addCleanup(popen.stop)

    def test_a_scene_scan_that_cannot_start_ends_in_an_error(self):
        clipper.scene_jobs["f" * 12] = {"state": "working"}
        self.addCleanup(clipper.scene_jobs.pop, "f" * 12, None)
        clipper.run_scenes("f" * 12)
        self.assertEqual(clipper.scene_jobs["f" * 12]["state"], "error")

    def test_a_failed_scene_scan_is_tried_again_next_time(self):
        clipper.scene_jobs["f" * 12] = {"state": "error", "message": "x"}
        self.addCleanup(clipper.scene_jobs.pop, "f" * 12, None)
        self.assertEqual(clipper.get_scenes("f" * 12)["state"], "error")
        with mock.patch.object(clipper.threading, "Thread") as thread:
            self.assertEqual(clipper.get_scenes("f" * 12)["state"], "working")
        thread.return_value.start.assert_called_once()

    def test_a_proxy_that_cannot_start_ends_in_an_error(self):
        self.addCleanup(clipper.proxies.pop, "f" * 12, None)
        clipper.run_proxy("f" * 12, self.video)
        self.assertEqual(clipper.proxies["f" * 12]["state"], "error")

    def test_a_cut_that_cannot_start_ends_in_an_error(self):
        self.addCleanup(clipper.cuts.pop, "c" * 16, None)
        clipper.run_cut("c" * 16, str(self.video), 0.0, 1.0)
        self.assertEqual(clipper.cuts["c" * 16]["state"], "error")


if __name__ == "__main__":
    unittest.main()
