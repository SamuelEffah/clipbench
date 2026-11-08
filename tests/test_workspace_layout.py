"""Everything the bench makes or downloads lives under one workspace folder, video ids are relative to it, and an
install laid out the old way is moved there once without losing proxies, transcripts, suggestions or projects."""
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import clipper  # noqa: E402
import youtube as yt  # noqa: E402
from store import Store  # noqa: E402
from tools import relocate, workspace  # noqa: E402


def short_hash(text):
    return hashlib.sha1(text.encode()).hexdigest()[:12]


class OneWorkspaceFolder(unittest.TestCase):
    def test_every_runtime_folder_sits_under_the_workspace(self):
        inside = [clipper.PROXY_DIR, clipper.PROJECT_DIR, clipper.BROLL_DIR, *clipper.LIBRARY_DIRS, *clipper.AUDIO_DIRS,
                  clipper.SHORT_DIR, clipper.DOWNLOAD_DIR, clipper.CUT_DIR, clipper.AVATAR_FILE, clipper.DATA_DIR]
        for path in inside:
            self.assertTrue(path.is_relative_to(clipper.WORKSPACE), f"{path} is outside the workspace")
        self.assertEqual(clipper.WORKSPACE, ROOT / "workspace")

    def test_setup_creates_only_workspace_folders_and_the_models_folder(self):
        for folder in workspace.FOLDERS:
            self.assertTrue(folder.startswith("workspace/") or folder == "scripts/models", folder)
        for stale in ("narration", "voices", "thumbs", "out", "cuts"):
            self.assertNotIn(f"workspace/{stale}", workspace.FOLDERS, f"{stale} is no longer used")

    def test_git_ignores_the_workspace_as_a_whole(self):
        ignore = (ROOT / ".gitignore").read_text().splitlines()
        self.assertIn("/workspace/", ignore)
        for old in ("/clips/", "/shorts/", "/data/", "/projects/", "/audio/", "/assets/channel/"):
            self.assertNotIn(old, ignore)

    def test_the_client_file_is_described_at_its_workspace_path(self):
        self.assertEqual(yt.CLIENT_FILE_HINT, "workspace/data/youtube_client.json")
        for page in ("index.html", "home.html"):
            self.assertIn("workspace/data", (ROOT / "scripts" / "clipper_ui" / page).read_text(), page)
        self.assertIn("workspace/data/youtube_client.json", (ROOT / "README.md").read_text())


class VideoIdsFollowTheWorkspace(unittest.TestCase):
    def test_a_video_inside_the_workspace_is_known_by_its_place_in_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(clipper, "WORKSPACE", Path(tmp)):
                self.assertEqual(clipper.media_key(Path(tmp) / "clips" / "a.mp4"), "clips/a.mp4")
                self.assertEqual(clipper.video_id(Path(tmp) / "clips" / "a.mp4"), short_hash("clips/a.mp4"))
                self.assertEqual(clipper.media_key("/elsewhere/b.mp4"), "/elsewhere/b.mp4")
                self.assertEqual(clipper.video_id("/elsewhere/b.mp4"), short_hash("/elsewhere/b.mp4"))


class MovingAnOldInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        r = self.root
        self.clip = r / "clips" / "ep.mp4"
        self.old_id = short_hash(str(self.clip))
        self.new_id = short_hash("clips/ep.mp4")
        for rel, body in {"clips/ep.mp4": b"video", f"clips/.proxy/{self.old_id}.jpg": b"thumb", "clips/.proxy/other.txt": b"x",
                          f"clips/.proxy/{self.old_id}.suggest.json": b"{}", "clips/.cuts/cut.mp4": b"cut",
                          f"data/transcripts/{self.old_id}.json": b"{}", "audio/a.mp3": b"sound", "projects/p.cuts.txt": b"cuts",
                          "shorts/001_p/video.mp4": b"short", "assets/channel/avatar.png": b"face", "assets/other.png": b"keep",
                          "narration/old.txt": b"legacy"}.items():
            (r / rel).parent.mkdir(parents=True, exist_ok=True)
            (r / rel).write_bytes(body)
        (r / "data" / "rendered").mkdir()
        (r / "data" / "rendered" / "p.json").write_text(json.dumps({"clips": [{"src": str(self.clip)}]}))
        store = Store(r / "data" / "clipbench.db")
        store.put_project("p", {"clips": [{"src": str(self.clip), "in": 1, "out": 2}], "audio": [{"src": str(r / "audio" / "a.mp3")}]})
        with sqlite3.connect(r / "data" / "clipbench.db") as db:
            db.execute("INSERT INTO favorites (data) VALUES (?)", (json.dumps({"src": str(self.clip)}),))
            db.execute("INSERT INTO video_owners (path, project) VALUES (?, ?)", (str(self.clip), "p"))
            db.execute("INSERT INTO extra_videos (path, added_at) VALUES (?, ?)", ("/elsewhere/b.mp4", 1.0))
            db.execute("INSERT INTO suggestion_reviews VALUES (?, ?, ?, ?, ?, ?)", (self.old_id, 1.0, 2.0, "keep", "{}", 1.0))

    def test_media_caches_and_stored_paths_all_move_together(self):
        done = relocate.relocate(self.root)
        ws = self.root / "workspace"
        self.assertTrue((ws / "clips" / "ep.mp4").is_file())
        self.assertFalse((self.root / "clips").exists())
        self.assertTrue((ws / "clips" / ".proxy" / f"{self.new_id}.jpg").is_file())
        self.assertTrue((ws / "clips" / ".proxy" / f"{self.new_id}.suggest.json").is_file())
        self.assertFalse((ws / "clips" / ".proxy" / f"{self.old_id}.jpg").exists())
        self.assertTrue((ws / "clips" / ".proxy" / "other.txt").is_file(), "files not keyed by a video id are left alone")
        self.assertTrue((ws / "data" / "transcripts" / f"{self.new_id}.json").is_file())
        self.assertTrue((ws / "channel" / "avatar.png").is_file())
        self.assertTrue((self.root / "assets" / "other.png").is_file())
        self.assertTrue((ws / "narration" / "old.txt").is_file(), "old folders move along even when nothing uses them")
        self.assertTrue((ws / "shorts" / "001_p" / "video.mp4").is_file())
        self.assertTrue((ws / "data" / "clipbench.db.before-workspace").is_file(), "the database is backed up first")
        new_clip = str(ws / "clips" / "ep.mp4")
        with sqlite3.connect(ws / "data" / "clipbench.db") as db:
            project = json.loads(db.execute("SELECT data FROM projects WHERE name='p'").fetchone()[0])
            self.assertEqual(project["clips"][0]["src"], new_clip)
            self.assertEqual(project["audio"][0]["src"], str(ws / "audio" / "a.mp3"))
            self.assertEqual(json.loads(db.execute("SELECT data FROM favorites").fetchone()[0])["src"], new_clip)
            self.assertEqual(db.execute("SELECT path FROM video_owners").fetchone()[0], new_clip)
            self.assertEqual(db.execute("SELECT path FROM extra_videos").fetchone()[0], "/elsewhere/b.mp4")
            self.assertEqual(db.execute("SELECT video FROM suggestion_reviews").fetchone()[0], self.new_id)
        self.assertEqual(json.loads((ws / "data" / "rendered" / "p.json").read_text())["clips"][0]["src"], new_clip)
        self.assertGreater(done["moved"], 0)
        again = relocate.relocate(self.root)
        self.assertEqual((again["moved"], again["renamed"], again["rewritten"]), (0, 0, 0), "a second run changes nothing")

    def test_a_fresh_install_has_nothing_to_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = relocate.relocate(Path(tmp))
        self.assertEqual((done["moved"], done["renamed"], done["rewritten"]), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
