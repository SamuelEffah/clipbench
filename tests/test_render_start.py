import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import clipper  # noqa: E402

class StartRender(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name, path in (("PROJECT_DIR", root / "projects"), ("SHORT_DIR", root / "shorts"), ("SNAPSHOT_DIR", root / "rendered")):
            path.mkdir()
            patch = mock.patch.object(clipper, name, path)
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(clipper.renders.clear)
        video = root / "a.mp4"
        video.write_bytes(b"v")
        self.clip = {"src": str(video), "in": 0, "out": 5}

    def test_a_bad_setting_does_not_leave_the_render_stuck(self):
        state = clipper.start_render("bad", {"clips": [self.clip], "layout": "nope"})
        self.assertEqual(state["state"], "error")
        self.assertIn("layout", state["message"])
        self.assertNotEqual(clipper.renders["bad"]["state"], "working")

    def test_rendering_does_not_write_a_title_or_description(self):
        with mock.patch.object(clipper.threading, "Thread"):
            clipper.start_render("quiet", {"clips": [self.clip], "hook": "A hook line"})
        folder = clipper.short_folder("quiet")
        self.assertEqual(sorted(p.name for p in folder.iterdir()), [])

    def test_a_render_remembers_the_project_it_was_made_from(self):
        project = {"clips": [self.clip], "hook": "Hello"}
        with mock.patch.object(clipper.threading, "Thread"):
            clipper.start_render("keep", project)
        self.assertEqual(clipper.rendered_project("keep"), project)

    def test_a_short_rendered_before_snapshots_has_none(self):
        self.assertIsNone(clipper.rendered_project("old"))

    def test_the_next_render_can_start_after_an_error(self):
        clipper.start_render("again", {"clips": [self.clip], "fade": 5})
        with mock.patch.object(clipper.threading, "Thread") as thread:
            state = clipper.start_render("again", {"clips": [self.clip]})
        self.assertEqual(state["state"], "working")
        started = [call.kwargs["target"] for call in thread.call_args_list]
        self.assertEqual(started, [clipper.run_render, clipper.describe_render])
        self.assertEqual(thread.return_value.start.call_count, 2)


if __name__ == "__main__":
    unittest.main()


class RenderCommand(unittest.TestCase):
    def test_every_render_keeps_its_clips_in_the_shared_cache(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(clipper, "CLIP_CACHE_DIR", Path(tmp) / "clipcache"), \
                mock.patch.object(clipper.subprocess, "Popen", side_effect=OSError("no ffmpeg")) as popen:
            clipper.renders["x"] = {"state": "working", "pct": 0, "total": 5}
            clipper.run_render("x", "", Path(tmp), [])
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[cmd.index("--cache") + 1], str(Path(tmp) / "clipcache"))
