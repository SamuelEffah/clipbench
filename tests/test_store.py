import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from store import Store  # noqa: E402


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "data" / "bench.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_project_round_trip_and_listing(self):
        self.assertEqual(self.store.list_projects(), [])
        self.store.put_project("b_one", {"hook": "x", "clips": []})
        self.store.put_project("a_two", {"hook": "y"})
        self.assertEqual(self.store.list_projects(), ["a_two", "b_one"])
        self.assertEqual(self.store.get_project("b_one"), {"hook": "x", "clips": []})
        self.assertIsNone(self.store.get_project("missing"))

    def test_project_overwrite_keeps_one_row(self):
        self.store.put_project("p", {"v": 1})
        self.store.put_project("p", {"v": 2})
        self.assertEqual(self.store.list_projects(), ["p"])
        self.assertEqual(self.store.get_project("p"), {"v": 2})

    def test_favorites_replace_keeps_order(self):
        self.store.replace_favorites([{"src": "a"}, {"src": "b"}])
        self.store.replace_favorites([{"src": "b"}, {"src": "c"}, {"src": "a"}])
        self.assertEqual([f["src"] for f in self.store.list_favorites()], ["b", "c", "a"])

    def test_extra_videos_are_unique(self):
        self.store.add_extra_video("/x/a.mp4")
        self.store.add_extra_video("/x/a.mp4")
        self.store.add_extra_video("/x/b.mp4")
        self.assertEqual(self.store.list_extra_videos(), ["/x/a.mp4", "/x/b.mp4"])

    def test_settings(self):
        self.assertIsNone(self.store.get_setting("k"))
        self.store.set_setting("k", {"a": 1})
        self.assertEqual(self.store.get_setting("k"), {"a": 1})
        self.store.delete_setting("k")
        self.assertIsNone(self.store.get_setting("k"))

    def test_a_suggestion_review_is_kept_per_moment_and_cleared_by_none(self):
        self.assertEqual(self.store.suggestion_reviews("vid1"), [])
        self.store.review_suggestion("vid1", 10.5, 42.0, "keep", {"text": "a line", "parts": {"hook": 70}})
        self.store.review_suggestion("vid1", 60.0, 90.0, "skip", {"text": "dull"})
        self.store.review_suggestion("vid2", 10.5, 42.0, "skip", {})
        rows = self.store.suggestion_reviews("vid1")
        self.assertEqual([(r["in"], r["out"], r["decision"]) for r in rows], [(10.5, 42.0, "keep"), (60.0, 90.0, "skip")])
        self.assertEqual(rows[0]["moment"], {"text": "a line", "parts": {"hook": 70}})
        self.store.review_suggestion("vid1", 10.5, 42.0, "skip", {"text": "a line"})
        self.assertEqual(self.store.suggestion_reviews("vid1")[0]["decision"], "skip")
        self.store.review_suggestion("vid1", 10.5, 42.0, None, {})
        self.assertEqual([r["out"] for r in self.store.suggestion_reviews("vid1")], [90.0])
        self.assertEqual([r["video"] for r in self.store.suggestion_reviews()], ["vid1", "vid2"])

    def test_uploads_lifecycle(self):
        first = self.store.add_upload("003_x", "Title", "private")
        self.assertEqual(self.store.latest_upload("003_x")["status"], "uploading")
        self.store.finish_upload(first, video_id="abc123")
        row = self.store.latest_upload("003_x")
        self.assertEqual((row["status"], row["video_id"]), ("done", "abc123"))
        second = self.store.add_upload("003_x", "Title 2", "private")
        self.store.fail_upload(second, "quota")
        latest = self.store.latest_upload("003_x")
        self.assertEqual((latest["status"], latest["message"]), ("error", "quota"))
        self.assertEqual(len(self.store.list_uploads("003_x")), 2)
        self.assertIsNone(self.store.latest_upload("nope"))

    def test_stale_uploads_are_marked_failed_on_open(self):
        uid = self.store.add_upload("s", "T", "private")
        reopened = Store(self.root / "data" / "bench.db")
        self.assertEqual(reopened.latest_upload("s")["id"], uid)
        self.assertEqual(reopened.latest_upload("s")["status"], "error")

    def test_import_legacy_files_once(self):
        legacy = self.root / "projects"
        legacy.mkdir()
        (legacy / "keep.json").write_text(json.dumps({"hook": "k"}))
        (legacy / "_favorites.json").write_text(json.dumps([{"src": "s"}]))
        (legacy / "_extra_videos.json").write_text(json.dumps(["/v.mp4"]))
        (legacy / "broken.json").write_text("{nope")
        self.assertEqual(self.store.import_legacy(legacy), 1)
        self.assertEqual(self.store.get_project("keep"), {"hook": "k"})
        self.assertEqual(self.store.list_favorites(), [{"src": "s"}])
        self.assertEqual(self.store.list_extra_videos(), ["/v.mp4"])
        (legacy / "keep.json").write_text(json.dumps({"hook": "changed"}))
        self.assertEqual(self.store.import_legacy(legacy), 0)
        self.assertEqual(self.store.get_project("keep"), {"hook": "k"})

    def test_db_file_is_private(self):
        self.assertEqual((self.root / "data" / "bench.db").stat().st_mode & 0o077, 0)


if __name__ == "__main__":
    unittest.main()


class LatestUploadPerformance(unittest.TestCase):
    def test_latest_reads_one_row_from_large_history(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'bench.db')
            with store._db() as db:
                db.executemany("INSERT INTO uploads (short,title,privacy,status,started_at) VALUES (?,?,?,?,?)",
                               [('one', str(i), 'private', 'done', i) for i in range(5000)])
            from unittest.mock import patch
            with patch.object(store, 'list_uploads', side_effect=AssertionError('Full history loaded')):
                self.assertEqual(store.latest_upload('one')['title'], '4999')
                self.assertIsNone(store.latest_upload('missing'))
            with store._db() as db:
                plan = list(db.execute("EXPLAIN QUERY PLAN SELECT * FROM uploads WHERE short=? ORDER BY id DESC LIMIT 1", ('one',)))
            self.assertTrue(any('uploads_short' in r['detail'] for r in plan))
