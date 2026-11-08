import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from store import Store  # noqa: E402


class Ownership(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "bench.db")

    def test_a_video_nobody_claimed_is_visible_to_every_project(self):
        self.assertTrue(self.store.visible("/v/old.mp4", "a"))
        self.assertTrue(self.store.visible("/v/old.mp4", "b"))

    def test_a_claimed_video_is_visible_only_to_its_project(self):
        self.store.claim_video("/v/new.mp4", "a")
        self.assertTrue(self.store.visible("/v/new.mp4", "a"))
        self.assertFalse(self.store.visible("/v/new.mp4", "b"))

    def test_two_projects_can_both_claim_the_same_file(self):
        self.store.claim_video("/v/new.mp4", "a")
        self.store.claim_video("/v/new.mp4", "b")
        self.store.claim_video("/v/new.mp4", "b")
        self.assertTrue(self.store.visible("/v/new.mp4", "b"))
        self.assertFalse(self.store.visible("/v/new.mp4", "c"))

    def test_unclaiming_forgets_every_owner(self):
        self.store.claim_video("/v/new.mp4", "a")
        self.store.unclaim_video("/v/new.mp4")
        self.assertTrue(self.store.visible("/v/new.mp4", "b"))

    def test_owners_lists_each_claimed_path(self):
        self.store.claim_video("/v/x.mp4", "a")
        self.store.claim_video("/v/x.mp4", "b")
        self.assertEqual(self.store.video_owners(), {"/v/x.mp4": {"a", "b"}})


class SavedClips(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "bench.db")
        self.store.replace_favorites([{"src": "legacy"}])

    def srcs(self, project=None):
        return [f["src"] for f in self.store.list_favorites(project)]

    def test_saving_in_a_project_hides_the_clip_from_the_others(self):
        self.store.replace_favorites_for("a", [{"src": "legacy"}, {"src": "mine"}])
        self.assertEqual(self.srcs("a"), ["legacy", "mine"])
        self.assertEqual(self.srcs("b"), ["legacy"])

    def test_the_whole_list_still_holds_everything(self):
        self.store.replace_favorites_for("a", [{"src": "legacy"}, {"src": "mine"}])
        self.store.replace_favorites_for("b", [{"src": "legacy"}, {"src": "theirs"}])
        self.assertEqual(sorted(self.srcs()), ["legacy", "mine", "theirs"])

    def test_removing_one_does_not_touch_another_projects_clips(self):
        self.store.replace_favorites_for("a", [{"src": "legacy"}, {"src": "mine"}])
        self.store.replace_favorites_for("b", [{"src": "legacy"}, {"src": "theirs"}])
        self.store.replace_favorites_for("a", [{"src": "legacy"}])
        self.assertEqual(sorted(self.srcs("b")), ["legacy", "theirs"])

    def test_resaving_a_shared_clip_does_not_claim_it(self):
        self.store.replace_favorites_for("a", [{"src": "legacy"}])
        self.assertEqual(self.srcs("b"), ["legacy"])

    def test_copying_a_project_copies_its_assets(self):
        self.store.replace_favorites_for("a", [{"src": "legacy"}, {"src": "mine"}])
        self.store.claim_video("/v/a.mp4", "a")
        self.store.copy_assets("a", "copy")
        self.assertEqual(sorted(self.srcs("copy")), ["legacy", "mine"])
        self.assertTrue(self.store.visible("/v/a.mp4", "copy"))
        self.assertEqual(self.srcs("b"), ["legacy"])

    def test_deleting_a_project_leaves_the_others_alone(self):
        for name in ("a", "b"):
            self.store.put_project(name, {"clips": []})
            self.store.claim_video(f"/v/{name}.mp4", name)
        self.store.replace_favorites_for("a", [{"src": "mine"}])
        self.store.delete_project("a")
        self.assertEqual(self.store.list_projects(), ["b"])
        self.assertEqual(self.srcs("a"), [])
        self.assertFalse(self.store.visible("/v/b.mp4", "a"))
        self.assertTrue(self.store.visible("/v/b.mp4", "b"))


class ServerRules(unittest.TestCase):
    def setUp(self):
        from scripts import clipper
        self.clipper = clipper
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "bench.db")
        self.dir = Path(self.tmp.name)
        for name, value in (("store", self.store), ("LIBRARY_DIRS", [self.dir])):
            patch = mock.patch.object(clipper, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.mine, self.theirs, self.old = self.dir / "mine.mp4", self.dir / "theirs.mp4", self.dir / "old.mp4"
        for f in (self.mine, self.theirs, self.old):
            f.write_bytes(b"x")
        self.store.claim_video(str(self.mine), "a")
        self.store.claim_video(str(self.theirs), "b")
        meta = {"duration": 5.0, "width": 10, "height": 10, "video": True}
        for name, value in (("probe", lambda p: meta), ("plays_directly", lambda p, m: True)):
            patch = mock.patch.object(clipper, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def names(self, project):
        return sorted(v["name"] for v in self.clipper.scan_library(project))

    def test_a_project_sees_its_own_videos_and_the_shared_ones(self):
        self.assertEqual(self.names("a"), ["mine.mp4", "old.mp4"])
        self.assertEqual(self.names("b"), ["old.mp4", "theirs.mp4"])

    def test_a_new_project_sees_only_the_shared_ones(self):
        self.assertEqual(self.names("fresh"), ["old.mp4"])

    def test_no_project_means_every_video(self):
        self.assertEqual(self.names(None), ["mine.mp4", "old.mp4", "theirs.mp4"])

    def test_a_finished_download_is_claimed_by_the_project_that_asked(self):
        clipper = self.clipper
        clipper.downloads["j"] = {"id": "j", "state": "working"}

        def done(job_id, *args):
            clipper.downloads[job_id] = {**clipper.downloads[job_id], "state": "done", "file": str(self.old)}
        clipper.guarded_download(done, "j", project="a")
        self.assertEqual(self.store.video_owners(), {str(self.mine): {"a"}, str(self.theirs): {"b"}, str(self.old): {"a"}})

    def test_a_failed_download_claims_nothing(self):
        clipper = self.clipper
        clipper.downloads["j"] = {"id": "j", "state": "working"}
        clipper.guarded_download(lambda job_id: clipper.downloads.__setitem__(job_id, {"id": job_id, "state": "error"}), "j", project="a")
        self.assertNotIn(str(self.old), self.store.video_owners())


if __name__ == "__main__":
    unittest.main()


class ClaimUsedVideos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "bench.db")

    def project(self, name, *paths):
        data = {"name": name, "clips": [{"src": p} for p in paths], "bank": []}
        self.store.put_project(name, data)
        return data

    def test_a_video_a_project_uses_stops_showing_in_new_projects(self):
        self.project("a", "/v/used.mp4")
        self.assertEqual(self.store.claim_used_videos(), 1)
        self.assertTrue(self.store.visible("/v/used.mp4", "a"))
        self.assertFalse(self.store.visible("/v/used.mp4", "brand-new"))

    def test_videos_no_project_uses_stay_shared(self):
        self.project("a", "/v/used.mp4")
        self.store.claim_used_videos()
        self.assertTrue(self.store.visible("/v/spare.mp4", "brand-new"))

    def test_projects_sharing_a_video_all_keep_it(self):
        self.project("a", "/v/both.mp4")
        self.project("b", "/v/both.mp4")
        self.store.claim_used_videos()
        self.assertTrue(self.store.visible("/v/both.mp4", "a"))
        self.assertTrue(self.store.visible("/v/both.mp4", "b"))
        self.assertFalse(self.store.visible("/v/both.mp4", "c"))

    def test_the_bank_counts_as_use(self):
        self.store.put_project("a", {"name": "a", "clips": [], "bank": [{"src": "/v/banked.mp4"}]})
        self.store.claim_used_videos()
        self.assertFalse(self.store.visible("/v/banked.mp4", "b"))

    def test_an_owned_video_is_left_alone(self):
        self.store.claim_video("/v/mine.mp4", "a")
        self.project("b", "/v/mine.mp4")
        self.assertEqual(self.store.claim_used_videos(), 0)
        self.assertFalse(self.store.visible("/v/mine.mp4", "b"))

    def test_a_project_saved_using_another_project_s_video_can_see_it_too(self):
        # A draft or a copy cut from a video its parent downloaded must keep seeing that video.
        self.store.claim_video("/v/mine.mp4", "a")
        data = self.project("a-draft-1", "/v/mine.mp4")
        self.assertEqual(self.store.claim_used_videos(data, "a-draft-1"), 1)
        self.assertTrue(self.store.visible("/v/mine.mp4", "a-draft-1"))
        self.assertTrue(self.store.visible("/v/mine.mp4", "a"))
        self.assertFalse(self.store.visible("/v/mine.mp4", "c"))
        self.assertEqual(self.store.claim_used_videos(data, "a-draft-1"), 0)

    def test_a_save_that_uses_nothing_unowned_skips_the_scan(self):
        self.store.claim_video("/v/mine.mp4", "a")
        data = self.project("a", "/v/mine.mp4")
        with mock.patch.object(self.store, "video_owners", return_value={"/v/mine.mp4": {"a"}}), \
                mock.patch.object(self.store, "_db", side_effect=AssertionError("scanned")):
            self.assertEqual(self.store.claim_used_videos(data), 0)


class OwnMedia(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "bench.db")

    def test_a_project_is_not_marked_unless_asked(self):
        self.assertFalse(self.store.own_media("old"))
        self.store.mark_own_media("new")
        self.assertTrue(self.store.own_media("new"))

    def test_deleting_a_project_forgets_the_mark(self):
        self.store.put_project("new", {"name": "new", "clips": [], "bank": []})
        self.store.mark_own_media("new")
        self.store.delete_project("new")
        self.assertFalse(self.store.own_media("new"))

    def test_shared_saved_clips_reach_old_projects_but_not_marked_ones(self):
        self.store.replace_favorites([{"src": "/v/a.mp4", "in": 0, "out": 1}])
        self.store.mark_own_media("new")
        self.assertEqual(len(self.store.list_favorites("old")), 1)
        self.assertEqual(self.store.list_favorites("new"), [])

    def test_existing_projects_are_marked_once(self):
        self.store.put_project("a", {"name": "a", "clips": [], "bank": []})
        self.assertEqual(self.store.mark_existing_projects_own_media(), 1)
        self.assertTrue(self.store.own_media("a"))
        self.store.put_project("b", {"name": "b", "clips": [], "bank": []})
        self.assertEqual(self.store.mark_existing_projects_own_media(), 0)
        self.assertFalse(self.store.own_media("b"))
