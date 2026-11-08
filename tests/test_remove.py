import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts import clipper  # noqa: E402


class RemoveVideoTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        self.clips, self.proxy, self.trash = self.dir / "clips", self.dir / "clips" / ".proxy", self.dir / "trash"
        self.proxy.mkdir(parents=True)
        self.store = mock.Mock()
        self.store.list_extra_videos.return_value = []
        self.store.list_projects.return_value = []
        self.store.iter_projects.side_effect = lambda: (self.store.get_project(n) for n in self.store.list_projects())
        self.store.list_favorites.return_value = []
        for name, value in (("LIBRARY_DIRS", [self.clips]), ("PROXY_DIR", self.proxy), ("TRASH_DIR", self.trash), ("store", self.store)):
            patch = mock.patch.object(clipper, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.video = self.clips / "a.mp4"
        self.video.write_bytes(b"x")
        self.vid = clipper.video_id(self.video)
        clipper.registry[self.vid] = self.video
        self.addCleanup(clipper.registry.pop, self.vid, None)

    def test_a_clips_folder_video_goes_to_the_trash_with_its_previews(self):
        for suffix in (".mp4", ".jpg", ".wave.json"):
            (self.proxy / f"{self.vid}{suffix}").write_bytes(b"p")
        self.assertEqual(clipper.remove_video(self.vid), "trash")
        self.assertFalse(self.video.exists())
        self.assertTrue((self.trash / "a.mp4").exists())
        self.assertEqual(list(self.proxy.glob(f"{self.vid}.*")), [])
        self.assertNotIn(self.vid, clipper.registry)

    def test_a_name_clash_in_the_trash_keeps_both_files(self):
        self.trash.mkdir()
        (self.trash / "a.mp4").write_bytes(b"old")
        clipper.remove_video(self.vid)
        self.assertEqual(len(list(self.trash.iterdir())), 2)
        self.assertEqual((self.trash / "a.mp4").read_bytes(), b"old")

    def test_a_video_added_by_path_is_only_unlisted(self):
        outside = self.dir / "elsewhere.mp4"
        outside.write_bytes(b"x")
        vid = clipper.video_id(outside)
        clipper.registry[vid] = outside
        self.addCleanup(clipper.registry.pop, vid, None)
        self.store.list_extra_videos.return_value = [str(outside)]
        self.assertEqual(clipper.remove_video(vid), "unlisted")
        self.assertTrue(outside.exists())
        self.store.remove_extra_video.assert_called_once_with(outside)

    def test_clips_cut_from_a_video_are_saved_as_files_before_it_goes(self):
        saved = []
        self.store.list_projects.return_value = ["p"]
        self.store.get_project.return_value = {"clips": [{"src": str(self.video), "in": 1.0, "out": 2.0}]}
        with mock.patch.object(clipper, "start_cut", side_effect=lambda *a: saved.append(a) or {"id": "x" * 16, "state": "ready"}), \
                mock.patch.object(clipper, "cut_status", return_value={"state": "ready"}):
            clipper.remove_video(self.vid)
        self.assertEqual(saved, [(str(self.video), 1.0, 2.0)])
        self.assertFalse(self.video.exists())

    def test_the_video_stays_if_a_clip_could_not_be_saved(self):
        self.store.list_projects.return_value = ["p"]
        self.store.get_project.return_value = {"clips": [{"src": str(self.video), "in": 1.0, "out": 2.0}]}
        with mock.patch.object(clipper, "start_cut", return_value={"id": "y" * 16, "state": "working"}), \
                mock.patch.object(clipper, "cut_status", return_value={"state": "error"}):
            with self.assertRaises(ValueError):
                clipper.remove_video(self.vid)
        self.assertTrue(self.video.exists())

    def test_a_clip_with_no_length_does_not_block_removing_its_video(self):
        self.store.list_projects.return_value = ["p"]
        self.store.get_project.return_value = {"clips": [{"src": str(self.video), "in": 0, "out": 0}]}
        self.assertEqual(clipper.remove_video(self.vid), "trash")
        self.assertFalse(self.video.exists())

    def test_an_unknown_video_is_refused(self):
        with self.assertRaises(ValueError):
            clipper.remove_video("0" * 12)

    def test_a_file_outside_the_library_is_never_trashed(self):
        outside = self.dir / "other.mp4"
        outside.write_bytes(b"x")
        vid = clipper.video_id(outside)
        clipper.registry[vid] = outside
        self.addCleanup(clipper.registry.pop, vid, None)
        with self.assertRaises(ValueError):
            clipper.remove_video(vid)
        self.assertTrue(outside.exists())


if __name__ == "__main__":
    unittest.main()
