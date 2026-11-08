import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import liverec


class Window(unittest.TestCase):
    def test_a_stretch_inside_the_recording(self):
        self.assertEqual(liverec.window(1000, 1010, 1040, 1100), (10, 30))

    def test_the_end_is_held_to_what_has_been_recorded(self):
        self.assertEqual(liverec.window(1000, 1090, 1130, 1100), (90, 10))

    def test_before_the_recording_started_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            liverec.window(1000, 990, 1020, 1100)
        self.assertIn("before the recording started", str(ctx.exception))

    def test_an_out_before_the_in_is_refused(self):
        with self.assertRaises(ValueError):
            liverec.window(1000, 1050, 1050, 1100)

    def test_nothing_recorded_yet_there(self):
        with self.assertRaises(ValueError):
            liverec.window(1000, 1100, 1110, 1100)


class Proc:
    def __init__(self, alive=True, err=""):
        self.alive, self.err, self.killed, self.pid = alive, err, False, 4242
        self.stderr = mock.Mock(read=lambda: err)

    def poll(self):
        return None if self.alive and not self.killed else 1

    def terminate(self):
        self.killed = True

    def wait(self, timeout=None):
        return 0


def fake_url(url="https://example.test/live.m3u8\n", code=0):
    return mock.Mock(return_value=subprocess.CompletedProcess([], code, url, ""))


class Reap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.rec = liverec.Recorder(self.folder, settle=0)

    def test_a_leftover_recorder_is_stopped_and_its_files_removed(self):
        (self.folder / "rec.pid").write_text("4242")
        (self.folder / "rec-1.ts").write_bytes(b"x")
        ps = subprocess.CompletedProcess([], 0, "/opt/homebrew/bin/ffmpeg -i u -t 7200 -c copy -f mpegts /x/rec-1.ts\n", "")
        with mock.patch("subprocess.run", return_value=ps), mock.patch("os.kill") as kill:
            self.rec.reap()
        kill.assert_called_once()
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_a_pid_that_is_now_something_else_is_left_alone(self):
        (self.folder / "rec.pid").write_text("4242")
        ps = subprocess.CompletedProcess([], 0, "/usr/bin/python3 other.py\n", "")
        with mock.patch("subprocess.run", return_value=ps), mock.patch("os.kill") as kill:
            self.rec.reap()
        kill.assert_not_called()

    def test_nothing_to_reap(self):
        self.rec.reap()


class Recording(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.rec = liverec.Recorder(Path(self.tmp.name), settle=0)

    def test_start_records_the_stream_and_remembers_where(self):
        proc = Proc()
        with mock.patch("subprocess.run", fake_url()), mock.patch("subprocess.Popen", return_value=proc) as popen:
            started = self.rec.start("yt-dlp", "ffmpeg", "https://www.twitch.tv/shroud")
        cmd = popen.call_args.args[0]
        self.assertIn("https://example.test/live.m3u8", cmd)
        self.assertEqual(cmd[cmd.index("-c") + 1], "copy")
        path, when = self.rec.active("https://www.twitch.tv/shroud")
        self.assertEqual((path.parent, when), (Path(self.tmp.name), started))
        self.assertIsNone(self.rec.active("https://www.twitch.tv/other"))

    def test_stop_ends_the_recording_but_keeps_the_file_for_cuts_in_flight(self):
        proc = Proc()
        with mock.patch("subprocess.run", fake_url()), mock.patch("subprocess.Popen", return_value=proc):
            self.rec.start("yt-dlp", "ffmpeg", "https://www.twitch.tv/shroud")
            path, _ = self.rec.active("https://www.twitch.tv/shroud")
            path.write_bytes(b"x")
            self.rec.stop()
        self.assertTrue(proc.killed)
        self.assertIsNone(self.rec.active("https://www.twitch.tv/shroud"))
        self.assertTrue(path.exists())

    def test_starting_again_clears_the_old_recording(self):
        with mock.patch("subprocess.run", fake_url()), mock.patch("subprocess.Popen", side_effect=[Proc(), Proc()]):
            self.rec.start("yt-dlp", "ffmpeg", "https://www.twitch.tv/shroud")
            old, _ = self.rec.active("https://www.twitch.tv/shroud")
            old.write_bytes(b"x")
            self.rec.start("yt-dlp", "ffmpeg", "https://www.twitch.tv/other")
        self.assertFalse(old.exists())

    def test_a_stream_that_cannot_be_opened_is_an_error(self):
        with mock.patch("subprocess.run", fake_url("", 1)):
            with self.assertRaises(ValueError):
                self.rec.start("yt-dlp", "ffmpeg", "https://www.twitch.tv/shroud")

    def test_a_recorder_that_dies_at_once_is_an_error(self):
        with mock.patch("subprocess.run", fake_url()), mock.patch("subprocess.Popen", return_value=Proc(alive=False, err="boom")):
            with self.assertRaises(ValueError):
                self.rec.start("yt-dlp", "ffmpeg", "https://www.twitch.tv/shroud")
        self.assertIsNone(self.rec.active("https://www.twitch.tv/shroud"))


class Server(unittest.TestCase):
    def setUp(self):
        import clipper
        self.clipper = clipper
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name, value in [("STREAMER_FILE", Path(self.tmp.name) / "s.json"), ("DOWNLOAD_DIR", Path(self.tmp.name) / "clips"),
                            ("recorder", liverec.Recorder(Path(self.tmp.name) / "live", settle=0))]:
            patcher = mock.patch.object(clipper, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_only_a_twitch_channel_can_be_recorded(self):
        for bad in ["https://www.youtube.com/@x", "https://www.twitch.tv/videos/1", "file:///etc/passwd", ""]:
            got, status = self.clipper.record_call("/api/live-record", {"url": bad})
            self.assertEqual(status, 400, bad)

    def test_a_download_of_a_recorded_channel_is_cut_from_the_recording(self):
        url = "https://www.twitch.tv/shroud"
        with mock.patch("subprocess.run", fake_url()), mock.patch("subprocess.Popen", return_value=Proc()):
            started = self.clipper.recorder.start("yt-dlp", "ffmpeg", url)
        with mock.patch("shutil.which", return_value="/bin/x"), mock.patch.object(self.clipper.threading, "Thread") as thread:
            self.clipper.start_download(url, live_wall=(started + 5, started + 15), title="shroud")
        args = thread.call_args.kwargs["args"]
        self.assertIs(args[0], self.clipper.run_recorded_cut)

    def test_a_cut_from_before_the_recording_is_an_error_the_page_can_show(self):
        self.clipper.downloads["j"] = {"id": "j", "state": "working", "pct": 0, "message": ""}
        with mock.patch("shutil.which", return_value="/bin/ffmpeg"):
            self.clipper.run_recorded_cut("j", Path(self.tmp.name) / "x.ts", 1000.0, (900.0, 920.0), "t")
        self.assertEqual(self.clipper.downloads["j"]["state"], "error")
        self.assertIn("before the recording started", self.clipper.downloads["j"]["message"])


if __name__ == "__main__":
    unittest.main()
