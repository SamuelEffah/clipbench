import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import clipper  # noqa: E402
import prepare  # noqa: E402
import suggest  # noqa: E402


def settle(queue, vid, timeout=5):
    gone = threading.Event()

    def watch():
        while queue.get(vid).get("state") in ("queued", "working"):
            gone.wait(0.01)
        gone.set()

    threading.Thread(target=watch, daemon=True).start()
    assert gone.wait(timeout), "queue never finished"


class QueueTests(unittest.TestCase):
    def test_runs_the_work_and_reports_steps(self):
        seen = []

        def work(vid, step):
            step("Scanning")
            seen.append(vid)

        q = prepare.Queue(work)
        q.add("a")
        settle(q, "a")
        self.assertEqual(seen, ["a"])
        self.assertEqual(q.get("a")["state"], "ready")

    def test_one_video_at_a_time_in_order(self):
        order, gate = [], threading.Event()

        def work(vid, step):
            order.append(("start", vid))
            if vid == "a":
                gate.wait(5)
            order.append(("end", vid))

        q = prepare.Queue(work)
        q.add("a")
        q.add("b")
        self.assertEqual(q.get("b")["state"], "queued")
        gate.set()
        settle(q, "a")
        settle(q, "b")
        self.assertEqual(order, [("start", "a"), ("end", "a"), ("start", "b"), ("end", "b")])

    def test_adding_a_video_already_waiting_does_not_repeat_it(self):
        count, gate = [], threading.Event()

        def work(vid, step):
            count.append(vid)
            gate.wait(5)

        q = prepare.Queue(work)
        q.add("a")
        q.add("a")
        q.add("a")
        gate.set()
        settle(q, "a")
        self.assertEqual(count, ["a"])

    def test_a_failure_is_an_error_and_the_next_video_still_runs(self):
        def work(vid, step):
            if vid == "bad":
                raise RuntimeError("boom")

        q = prepare.Queue(work)
        q.add("bad")
        q.add("good")
        settle(q, "bad")
        settle(q, "good")
        self.assertEqual(q.get("bad")["state"], "error")
        self.assertEqual(q.get("good")["state"], "ready")

    def test_a_finished_video_can_be_prepared_again(self):
        count = []
        q = prepare.Queue(lambda vid, step: count.append(vid))
        q.add("a")
        settle(q, "a")
        q.add("a")
        settle(q, "a")
        self.assertEqual(count, ["a", "a"])

    def test_unknown_video_has_no_state(self):
        self.assertEqual(prepare.Queue(lambda v, s: None).get("zzz"), {"state": "none"})


class PrepareVideo(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.src = Path(tmp.name) / "v.mp4"
        self.src.write_bytes(b"x")
        self.vid = "d" * 12
        clipper.registry[self.vid] = self.src
        self.addCleanup(clipper.registry.pop, self.vid, None)
        self.steps, self.calls = [], []
        self.start(mock.patch.object(clipper, "PREPARE_POLL", 0.01))
        for name in ("get_scenes", "start_index", "start_suggest"):
            self.start(mock.patch.object(clipper, name, side_effect=lambda *a, n=name, **k: self.calls.append(n)))
        self.start(mock.patch.object(clipper.suggest, "warm", side_effect=lambda m: self.calls.append("warm")))
        self.start(mock.patch.object(clipper.suggest, "ollama_models", return_value=[]))

    def start(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_it(self, cues, engine="mlx"):
        with mock.patch.object(clipper, "dialogue_cues", side_effect=cues), \
             mock.patch.object(clipper, "speech_engine", return_value=engine):
            clipper.prepare_video(self.vid, self.steps.append)

    def test_a_video_with_subtitles_skips_listening(self):
        self.run_it([[(0, 1, "hi")], [(0, 1, "hi")]])
        self.assertEqual(self.calls, ["get_scenes", "warm", "start_suggest"])
        self.assertEqual(self.steps, ["Scanning", "Finding clips"])

    def test_an_unheard_video_is_listened_to_while_it_scans(self):
        self.run_it([None, [(0, 1, "hi")]])
        self.assertEqual(self.calls, ["get_scenes", "start_index", "warm", "start_suggest"])
        self.assertEqual(self.steps, ["Scanning", "Listening", "Finding clips"])

    def test_no_way_to_listen_stops_after_the_scan(self):
        self.run_it([None, None], engine=None)
        self.assertEqual(self.calls, ["get_scenes"])

    def test_a_video_that_is_gone_is_an_error(self):
        self.src.unlink()
        with self.assertRaises(ValueError):
            clipper.prepare_video(self.vid, lambda s: None)


class AfterDownload(unittest.TestCase):
    def test_a_finished_download_is_queued_and_registered(self):
        path = Path("/tmp/some video.mp4")
        vid = clipper.video_id(path)
        self.addCleanup(clipper.registry.pop, vid, None)
        with mock.patch.object(clipper.prepare_queue, "add") as add, mock.patch.object(clipper, "auto_prepare", True):
            clipper.prepare_after_download(str(path))
        add.assert_called_once_with(vid)
        self.assertEqual(clipper.registry[vid], path)

    def test_switched_off_does_nothing(self):
        with mock.patch.object(clipper.prepare_queue, "add") as add, mock.patch.object(clipper, "auto_prepare", False):
            clipper.prepare_after_download("/tmp/x.mp4")
        add.assert_not_called()

    def test_a_failure_never_reaches_the_download(self):
        self.addCleanup(clipper.registry.pop, clipper.video_id(Path("/tmp/y.mp4")), None)
        with mock.patch.object(clipper.prepare_queue, "add", side_effect=RuntimeError("x")), \
             mock.patch.object(clipper, "auto_prepare", True):
            clipper.prepare_after_download("/tmp/y.mp4")

    def test_guarded_download_prepares_a_done_download(self):
        def done(job_id):
            clipper.downloads[job_id] = {"id": job_id, "state": "done", "file": "/tmp/z.mp4"}

        self.addCleanup(clipper.downloads.pop, "jz", None)
        with mock.patch.object(clipper, "prepare_after_download") as prep:
            clipper.guarded_download(done, "jz")
        prep.assert_called_once_with("/tmp/z.mp4")


class Warm(unittest.TestCase):
    def test_asks_the_server_to_keep_the_model_loaded(self):
        with mock.patch.object(suggest.urllib.request, "urlopen") as op:
            suggest.warm("qwen2.5:3b")
        req = op.call_args.args[0]
        self.assertTrue(req.full_url.endswith("/api/generate"))
        self.assertIn(b"keep_alive", req.data)

    def test_no_model_does_nothing(self):
        with mock.patch.object(suggest.urllib.request, "urlopen") as op:
            suggest.warm(None)
        op.assert_not_called()

    def test_a_server_that_is_down_is_ignored(self):
        with mock.patch.object(suggest.urllib.request, "urlopen", side_effect=suggest.urllib.error.URLError("down")):
            suggest.warm("m")


if __name__ == "__main__":
    unittest.main()


class ImportedVideos(unittest.TestCase):
    def handler(self, body=b"", query="name=clip.mp4"):
        import io
        h = mock.Mock(path=f"/api/upload-video?{query}")
        h.headers = {"Content-Length": str(len(body))}
        h.rfile = io.BytesIO(body)
        h.send_json = mock.Mock()
        return h

    def test_an_uploaded_video_is_prepared(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "clip.mp4"
            h = self.handler(b"data")
            with mock.patch.object(clipper, "upload_target", return_value=target), \
                 mock.patch.object(clipper, "prepare_after_download") as prep:
                clipper.Handler.receive_video(h, "clip.mp4")
            prep.assert_called_once_with(target)

    def test_uploaded_audio_and_broll_are_not_prepared(self):
        with tempfile.TemporaryDirectory() as tmp:
            for kwargs in ({"audio": True}, {"broll": True}):
                target = Path(tmp) / "x.mp4"
                with mock.patch.object(clipper, "upload_target", return_value=target), \
                     mock.patch.object(clipper, "prepare_after_download") as prep:
                    clipper.Handler.receive_video(self.handler(b"data"), "x.mp4", **kwargs)
                prep.assert_not_called()
                target.unlink(missing_ok=True)

    def test_a_failed_upload_is_not_prepared(self):
        h = self.handler(b"")
        with mock.patch.object(clipper, "upload_target", return_value=Path("/tmp/none.mp4")), \
             mock.patch.object(clipper, "prepare_after_download") as prep:
            clipper.Handler.receive_video(h, "none.mp4")
        prep.assert_not_called()
