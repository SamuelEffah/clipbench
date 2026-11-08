import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts import clipper  # noqa: E402


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is needed")
class CutTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.src = self.dir / "src.mp4"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=d=6:s=160x90:r=30",
                        "-f", "lavfi", "-i", "sine=d=6", "-shortest", "-pix_fmt", "yuv420p", str(self.src)], check=True)
        patch = mock.patch.object(clipper, "CUT_DIR", self.dir / "cuts")
        patch.start()
        self.addCleanup(patch.stop)
        clipper.registry["feedfacecafe"] = self.src
        self.addCleanup(clipper.registry.pop, "feedfacecafe", None)

    def wait(self, cid):
        for _ in range(100):
            state = clipper.cut_status(cid)
            if state["state"] != "working":
                return state
            time.sleep(0.1)
        self.fail("the cut never finished")

    def duration(self, path):
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                             capture_output=True, text=True, check=True).stdout
        return float(json.loads(out)["format"]["duration"])

    def test_a_cut_is_its_own_playable_file_of_the_right_length(self):
        job = clipper.start_cut(str(self.src), 1.0, 3.5)
        self.assertEqual(self.wait(job["id"])["state"], "ready")
        self.assertAlmostEqual(self.duration(clipper.cut_path(job["id"])), 2.5, delta=0.15)

    def test_asking_again_reuses_the_file(self):
        first = clipper.start_cut(str(self.src), 1.0, 2.0)
        self.wait(first["id"])
        again = clipper.start_cut(str(self.src), 1.0, 2.0)
        self.assertEqual((again["id"], again["state"]), (first["id"], "ready"))

    def test_a_different_range_is_a_different_file(self):
        self.assertNotEqual(clipper.cut_id(str(self.src), 1.0, 2.0), clipper.cut_id(str(self.src), 1.0, 2.5))

    def test_a_video_outside_the_library_is_refused(self):
        other = self.dir / "other.mp4"
        shutil.copy(self.src, other)
        with self.assertRaises(ValueError):
            clipper.start_cut(str(other), 1.0, 2.0)

    def test_a_bad_range_is_refused(self):
        for start, end in ((2.0, 1.0), (-1.0, 2.0), (0.0, clipper.MAX_CUT_SECONDS + 1)):
            with self.assertRaises(ValueError):
                clipper.start_cut(str(self.src), start, end)

    def test_unfinished_and_old_cuts_are_pruned(self):
        cuts = self.dir / "cuts"
        cuts.mkdir()
        (cuts / "a.part.mp4").write_bytes(b"x")
        old = cuts / "old.mp4"
        old.write_bytes(b"x")
        stamp = time.time() - (clipper.CUT_PRUNE_DAYS + 1) * 86400
        __import__("os").utime(old, (stamp, stamp))
        (cuts / "new.mp4").write_bytes(b"x")
        store = mock.Mock()
        store.iter_projects.side_effect = lambda: (store.get_project(n) for n in store.list_projects())
        store.list_projects.return_value = []
        store.list_favorites.return_value = []
        with mock.patch.object(clipper, "store", store):
            clipper.prune_cuts()
        self.assertEqual([f.name for f in cuts.iterdir()], ["new.mp4"])

    def test_an_old_file_a_clip_still_uses_is_never_pruned(self):
        job = clipper.start_cut(str(self.src), 1.0, 2.0)
        self.wait(job["id"])
        stamp = time.time() - (clipper.CUT_PRUNE_DAYS + 1) * 86400
        __import__("os").utime(clipper.cut_path(job["id"]), (stamp, stamp))
        store = mock.Mock()
        store.iter_projects.side_effect = lambda: (store.get_project(n) for n in store.list_projects())
        store.list_projects.return_value = []
        store.list_favorites.return_value = [{"src": str(self.src), "in": 1.0, "out": 2.0}]
        with mock.patch.object(clipper, "store", store):
            clipper.prune_cuts()
        self.assertTrue(clipper.cut_path(job["id"]).exists())

    def test_warming_cuts_every_clip_any_project_or_saved_list_uses(self):
        other = self.src
        store = mock.Mock()
        store.iter_projects.side_effect = lambda: (store.get_project(n) for n in store.list_projects())
        store.list_projects.return_value = ["a", "b"]
        store.get_project.side_effect = lambda n: {"a": {"clips": [{"src": str(other), "in": 1, "out": 2}],
                                                         "bank": [{"src": str(other), "in": 1, "out": 2}]},
                                                  "b": {"clips": [{"src": str(other), "in": 3, "out": 4}]}}[n]
        store.list_favorites.return_value = [{"src": str(other), "in": 5, "out": 5.5}, {"nonsense": True}]
        store.list_extra_videos.return_value = [str(other)]
        with mock.patch.object(clipper, "store", store), mock.patch.object(clipper, "LIBRARY_DIRS", [self.dir]):
            self.assertEqual(clipper.all_clip_ranges(), [(str(other), 1.0, 2.0), (str(other), 3.0, 4.0), (str(other), 5.0, 5.5)])
            clipper.warm_cuts()
            for _ in range(100):
                if clipper.warm_progress()["done"] == 3:
                    break
                time.sleep(0.1)
        self.assertEqual(clipper.warm_progress(), {"total": 3, "done": 3})

    def test_a_saved_clip_is_found_again_without_its_source(self):
        job = clipper.start_cut(str(self.src), 1.0, 2.0)
        self.wait(job["id"])
        self.src.unlink()
        clipper.registry.pop("feedfacecafe", None)
        self.assertEqual(clipper.indexed_cut(str(self.src), 1.0, 2.0), job["id"])
        self.assertEqual(clipper.start_cut(str(self.src), 1.0, 2.0), {"id": job["id"], "state": "ready"})
        self.assertIsNone(clipper.indexed_cut(str(self.src), 1.0, 2.5))

    def test_a_clip_whose_video_is_gone_renders_from_its_saved_file(self):
        job = clipper.start_cut(str(self.src), 1.0, 3.0)
        self.wait(job["id"])
        self.src.unlink()
        project = {"clips": [{"src": str(self.src), "in": 1.0, "out": 3.0}]}
        with mock.patch.object(clipper, "PROJECT_DIR", self.dir / "projects"):
            text, _ = clipper.export_cuts("gone", project)
            line = [l for l in text.splitlines() if " | " in l][0]
            source, _, span = line.partition(" | ")
            self.assertEqual(source, str(clipper.cut_path(job["id"])))
            start, end = (float(x) for x in span.split(" - "))
            self.assertEqual(start, 0.0)
            self.assertAlmostEqual(end, 2.0, delta=0.2)
            with self.assertRaises(ValueError):
                clipper.export_cuts("gone", {"clips": [{"src": str(self.src), "in": 5.0, "out": 5.5}]})

    def test_probe_is_remembered_until_the_file_changes(self):
        with mock.patch.object(clipper, "_probe", wraps=clipper._probe) as probe:
            clipper.probe(self.src)
            clipper.probe(self.src)
            self.assertEqual(probe.call_count, 1)
            self.src.write_bytes(self.src.read_bytes() + b"\0")
            clipper.probe(self.src)
            self.assertEqual(probe.call_count, 2)


if __name__ == "__main__":
    unittest.main()
