import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import clipper

FAKE = """#!/bin/sh
echo "[download] 100.0% of 1.00MiB"
echo "{path}"
"""


class Download(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name).resolve()
        patch = mock.patch.object(clipper, "DOWNLOAD_DIR", self.dir)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def fake_exe(self, path):
        exe = self.dir / "fake-yt-dlp"
        exe.write_text(FAKE.format(path=path))
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        return str(exe)

    def run_job(self, exe, playable=True):
        clipper.downloads["job"] = {"id": "job", "state": "working", "pct": 0, "message": "Starting"}
        with mock.patch.object(clipper, "playable", return_value=playable):
            clipper.run_download("job", exe, "https://example.com/v")
        return clipper.downloads.pop("job")

    def test_an_empty_file_is_an_error_and_removed(self):
        empty = self.dir / "Ended-stream-16-26.mp4"
        empty.write_bytes(b"\0" * 261)
        job = self.run_job(self.fake_exe(empty), playable=False)
        self.assertEqual(job["state"], "error")
        self.assertIn("came back empty", job["message"])
        self.assertFalse(empty.exists())

    def test_a_file_downloaded_before_is_found(self):
        old = self.dir / "Clip-abc.mp4"
        old.write_text("x")
        long_ago = time.time() - 86400
        os.utime(old, (long_ago, long_ago))
        job = self.run_job(self.fake_exe(old))
        self.assertEqual(job["state"], "done")
        self.assertEqual(job["file"], str(old))

    def test_the_printed_file_wins_over_a_newer_one(self):
        mine, other = self.dir / "mine.mp4", self.dir / "other.mp4"
        mine.write_text("x")
        exe = self.fake_exe(mine)
        other.write_text("y")
        later = time.time() + 5
        os.utime(other, (later, later))
        self.assertEqual(self.run_job(exe)["file"], str(mine))

    def test_a_download_that_crashes_ends_in_an_error(self):
        class Now:
            def __init__(self, target, args, daemon):
                self.run = lambda: target(*args)

            def start(self):
                self.run()

        gone = FileNotFoundError("other.f137.mp4")
        with mock.patch.object(clipper.shutil, "which", return_value="/bin/yt-dlp"), \
                mock.patch.object(clipper.threading, "Thread", Now), \
                mock.patch.object(clipper, "run_download", side_effect=gone), \
                mock.patch.object(clipper, "run_live_cut", side_effect=gone):
            for live in (None, (1.0, 2.0)):
                job = clipper.start_download("https://example.com/v", live_wall=live)
                state = clipper.downloads.pop(job["id"])
                self.assertEqual(state["state"], "error")
                self.assertIn("other.f137.mp4", state["message"])

    def test_only_videos_in_the_download_folder_count(self):
        self.assertFalse(clipper.downloaded_file("[download] Destination: /x.mp4"))
        self.assertFalse(clipper.downloaded_file("/etc/hosts"))
        outside = Path(tempfile.gettempdir()) / "nothing-here.mp4"
        self.assertFalse(clipper.downloaded_file(str(outside)))


class Playable(unittest.TestCase):
    def check(self, meta, want=0):
        with mock.patch.object(clipper, "probe", return_value=meta):
            return clipper.playable(Path("x.mp4"), want)

    def test_needs_a_picture_and_length(self):
        self.assertTrue(self.check({"video": "h264", "duration": 8.0}, 8))
        self.assertFalse(self.check({"video": None, "duration": 8.0}))
        self.assertFalse(self.check({"video": "h264", "duration": 0}))
        self.assertFalse(self.check(None))

    def test_a_cut_much_shorter_than_asked_is_rejected(self):
        self.assertFalse(self.check({"video": "h264", "duration": 1.0}, 8))
        self.assertTrue(self.check({"video": "h264", "duration": 7.4}, 8))


if __name__ == "__main__":
    unittest.main()
