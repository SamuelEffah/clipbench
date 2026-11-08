import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import shorts  # noqa: E402


class ListShortsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def make(self, folder, video=True, title="", mtime=None):
        d = self.root / folder
        d.mkdir()
        if video:
            f = d / "video.mp4"
            f.write_bytes(b"v" * 1000)
            if mtime:
                os.utime(f, (mtime, mtime))
        if title:
            (d / "title.txt").write_text(title + "\n")
        return d

    def listing(self, projects=("hello",), states=None):
        states = states or {}
        return shorts.list_shorts(self.root, projects, lambda n: states.get(n, {"state": "none"}), lambda p: 26.6)

    def test_newest_first_and_name_is_folder_without_number(self):
        self.make("001_old", mtime=1000)
        self.make("003_new", mtime=3000)
        self.make("002_mid", mtime=2000)
        self.assertEqual([s["name"] for s in self.listing()], ["new", "mid", "old"])

    def test_fields(self):
        self.make("004_hello", title="My title #shorts", mtime=5000)
        (row,) = self.listing()
        self.assertEqual((row["folder"], row["title"], row["size"], row["duration"]), ("004_hello", "My title #shorts", 1000, 26.6))
        self.assertEqual((row["rendered_at"], row["has_project"], row["upload"]["state"]), (5000, True, "none"))

    def test_unrendered_folders_and_stray_files_are_skipped(self):
        self.make("005_nothing", video=False)
        (self.root / "notes.txt").write_text("x")
        (self.root / "badname").mkdir()
        self.make("006_ok")
        self.assertEqual([s["name"] for s in self.listing()], ["ok"])

    def test_project_flag_and_upload_state(self):
        self.make("007_ghost")
        (row,) = self.listing(projects=(), states={"ghost": {"state": "done", "video_id": "x"}})
        self.assertFalse(row["has_project"])
        self.assertEqual(row["upload"]["video_id"], "x")

    def test_an_upload_of_an_earlier_render_does_not_count(self):
        self.make("001_old", mtime=2000)
        done = {"state": "done", "video_id": "x", "finished_at": 1000}
        (row,) = self.listing(projects=(), states={"old": done})
        self.assertEqual(row["upload"], {"state": "none"})

    def test_an_upload_after_the_render_counts(self):
        self.make("001_new", mtime=1000)
        done = {"state": "done", "video_id": "x", "finished_at": 2000}
        (row,) = self.listing(projects=(), states={"new": done})
        self.assertEqual(row["upload"]["video_id"], "x")

    def test_an_upload_still_going_counts_whatever_the_video_age(self):
        self.make("001_live", mtime=2000)
        (row,) = self.listing(projects=(), states={"live": {"state": "uploading", "pct": 10}})
        self.assertEqual(row["upload"]["state"], "uploading")

    def test_missing_directory_is_empty(self):
        self.assertEqual(shorts.list_shorts(self.root / "nope", [], lambda n: {}, lambda p: 1), [])

    def test_unreadable_duration_is_none(self):
        self.make("008_x")
        rows = shorts.list_shorts(self.root, [], lambda n: {"state": "none"}, lambda p: None)
        self.assertIsNone(rows[0]["duration"])


class ThumbnailTest(unittest.TestCase):
    def test_thumb_is_cached_until_the_video_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            video = folder / "video.mp4"
            video.write_bytes(b"v")
            calls = []

            def fake_ffmpeg(src, dest):
                calls.append(1)
                Path(dest).write_bytes(b"jpg")
                return True

            self.assertEqual(shorts.thumbnail(folder, fake_ffmpeg), folder / "thumb.jpg")
            shorts.thumbnail(folder, fake_ffmpeg)
            self.assertEqual(len(calls), 1)
            os.utime(video, (os.path.getmtime(video) + 10,) * 2)
            shorts.thumbnail(folder, fake_ffmpeg)
            self.assertEqual(len(calls), 2)

    def test_failed_thumbnail_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "video.mp4").write_bytes(b"v")
            self.assertIsNone(shorts.thumbnail(folder, lambda s, d: False))


if __name__ == "__main__":
    unittest.main()
