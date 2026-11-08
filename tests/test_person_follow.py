import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import person_follow as pf  # noqa: E402

W, H = 320, 180


class Array:
    def __init__(self, data):
        self.data = np.array(data)

    def cpu(self):
        return self

    def numpy(self):
        return self.data


class Boxes:
    def __init__(self, found):
        self.id = Array([i for i, _ in found]) if found else None
        self.xyxy = Array([b for _, b in found]) if found else Array(np.zeros((0, 4)))


class Result:
    def __init__(self, found):
        self.boxes = Boxes(found)


class FakeModel:
    """Stands in for YOLO: reports the people it was told to for each frame, in order."""
    def __init__(self, script):
        self.script, self.n = script, 0

    def track(self, frame, **kwargs):
        found = self.script[min(self.n, len(self.script) - 1)]
        self.n += 1
        return [Result(found)]


def frame_with(people):
    """A frame with a rectangle per (box, BGR colour)."""
    img = np.full((H, W, 3), 90, np.uint8)
    for (x1, y1, x2, y2), colour in people:
        img[y1:y2, x1:x2] = colour
    return img


WHITE, GREEN = (240, 240, 240), (40, 160, 40)
BOX = {"x": 0.25, "y": 0.2, "w": 0.15, "h": 0.5}


class Matching(unittest.TestCase):
    def test_overlap(self):
        self.assertAlmostEqual(pf.overlap((0, 0, 10, 10), (0, 0, 10, 10)), 1.0)
        self.assertEqual(pf.overlap((0, 0, 10, 10), (20, 20, 30, 30)), 0.0)
        self.assertAlmostEqual(pf.overlap((0, 0, 10, 10), (5, 0, 15, 10)), 1 / 3)

    def test_picks_the_person_under_the_box(self):
        people = [(1, (0, 0, 30, 100)), (2, (200, 0, 230, 100))]
        self.assertEqual(pf.pick_person(people, (205, 10, 225, 90)), 2)

    def test_a_person_whose_middle_is_in_a_small_box_still_counts(self):
        self.assertEqual(pf.pick_person([(7, (0, 0, 100, 200))], (40, 90, 60, 110)), 7)

    def test_no_one_in_the_box(self):
        self.assertIsNone(pf.pick_person([(1, (0, 0, 30, 100))], (200, 0, 230, 100)))
        self.assertIsNone(pf.pick_person([], (0, 0, 10, 10)))

    def test_thin_keeps_the_ends_and_the_limit(self):
        s = [{"t": i} for i in range(1000)]
        out = pf.thin(s, 100)
        self.assertEqual(len(out), 100)
        self.assertEqual((out[0]["t"], out[-1]["t"]), (0, 999))
        self.assertEqual(pf.thin(s[:10], 100), s[:10])

    def test_first_sample_is_moved_to_the_middle_of_the_box(self):
        s = [{"t": 0, "x": 0.6, "y": 0.4, "w": 0.1, "h": 0.3}, {"t": 1, "x": 0.7, "y": 0.4, "w": 0.1, "h": 0.3}]
        out = pf.aligned(s, {"x": 0.2, "y": 0.1, "w": 0.2, "h": 0.2})
        self.assertEqual((out[0]["x"], out[0]["y"]), (0.3, 0.2))
        self.assertAlmostEqual(out[1]["x"], 0.4)


class Looks(unittest.TestCase):
    def test_same_jersey_matches_and_another_colour_does_not(self):
        a = frame_with([((20, 20, 60, 120), WHITE)])
        b = frame_with([((200, 30, 240, 130), WHITE)])
        c = frame_with([((200, 30, 240, 130), GREEN)])
        look = pf.signature(a, (20, 20, 60, 120))
        self.assertGreater(pf.likeness(look, pf.signature(b, (200, 30, 240, 130))), pf.SAME_LOOK)
        self.assertLess(pf.likeness(look, pf.signature(c, (200, 30, 240, 130))), pf.SAME_LOOK)

    def test_brightness_tells_white_from_dark(self):
        a = frame_with([((20, 20, 60, 120), WHITE)])
        b = frame_with([((20, 20, 60, 120), (30, 30, 30))])
        self.assertLess(pf.likeness(pf.signature(a, (20, 20, 60, 120)), pf.signature(b, (20, 20, 60, 120))), pf.SAME_LOOK)

    def test_choose_keeps_the_tracked_person_while_they_look_the_same(self):
        box1, box2 = (20, 20, 60, 120), (200, 20, 240, 120)
        frame = frame_with([(box1, WHITE), (box2, WHITE)])
        look = pf.signature(frame, box1)
        self.assertEqual(pf.choose([(1, box1), (2, box2)], 1, box1, look, frame), (1, box1))

    def test_choose_will_not_swap_to_a_defender_in_another_colour(self):
        box1, box2 = (20, 20, 60, 120), (50, 20, 90, 120)
        look = pf.signature(frame_with([(box1, WHITE)]), box1)
        frame = frame_with([(box1, GREEN), (box2, GREEN)])
        target, found = pf.choose([(1, box1), (2, box2)], 1, box1, look, frame)
        self.assertIsNone(found)

    def test_choose_finds_the_player_again_under_a_new_id(self):
        box1, box2 = (20, 20, 60, 120), (60, 25, 100, 125)
        look = pf.signature(frame_with([(box1, WHITE)]), box1)
        frame = frame_with([(box2, WHITE)])
        self.assertEqual(pf.choose([(9, box2)], 1, box1, look, frame), (9, box2))

    def test_choose_ignores_a_lookalike_of_the_wrong_size(self):
        box1, tiny = (20, 20, 60, 120), (60, 80, 70, 100)
        look = pf.signature(frame_with([(box1, WHITE)]), box1)
        frame = frame_with([(tiny, WHITE)])
        self.assertIsNone(pf.choose([(9, tiny)], 1, box1, look, frame)[1])


class Cuts(unittest.TestCase):
    def test_a_shifted_picture_is_a_pan_and_a_new_picture_is_a_cut(self):
        rng = np.random.default_rng(1)
        base = cv_blur(rng.integers(0, 255, (360, 640, 3), dtype=np.uint8))
        panned = np.roll(base, 12, axis=1)
        other = cv_blur(rng.integers(0, 255, (360, 640, 3), dtype=np.uint8))
        self.assertFalse(pf.is_cut(base, panned))
        self.assertTrue(pf.is_cut(base, other))


def cv_blur(img):
    import cv2
    return cv2.GaussianBlur(img, (0, 0), 1)


class Leg(unittest.TestCase):
    def frames(self, n):
        return [(i / 15, frame_with([((60, 40, 100, 140), WHITE)])) for i in range(n)]

    def run_leg(self, script, frames):
        return pf.run_leg(iter(frames), BOX, lambda: FakeModel(script))

    def test_follows_the_person_in_the_box_and_starts_at_its_middle(self):
        script = [[(5, (60 + 4 * i, 40, 100 + 4 * i, 140))] for i in range(6)]
        out = self.run_leg(script, self.frames(6))
        self.assertEqual(len(out), 6)
        self.assertAlmostEqual(out[0]["x"], 0.325)
        self.assertGreater(out[5]["x"], out[0]["x"])

    def test_nobody_in_the_box_raises(self):
        with self.assertRaises(pf.NoPerson):
            self.run_leg([[(1, (250, 10, 300, 150))]], self.frames(3))

    def test_holds_the_last_position_when_the_person_is_lost(self):
        seen = [(5, (60, 40, 100, 140))]
        out = self.run_leg([seen, seen, [], []], self.frames(4))
        self.assertEqual(out[1]["x"], out[3]["x"])

    def test_stops_following_after_a_cut(self):
        rng = np.random.default_rng(2)
        shot_a = cv_blur(rng.integers(0, 255, (180, 320, 3), dtype=np.uint8))
        shot_b = cv_blur(rng.integers(0, 255, (180, 320, 3), dtype=np.uint8))
        shot_a[40:140, 60:100] = WHITE
        shot_b[20:120, 200:240] = WHITE
        frames = [(0, shot_a), (1 / 15, shot_a), (2 / 15, shot_b), (3 / 15, shot_b)]
        script = [[(5, (60, 40, 100, 140))], [(5, (60, 40, 100, 140))], [(5, (200, 20, 240, 120))], [(5, (200, 20, 240, 120))]]
        out = self.run_leg(script, frames)
        self.assertEqual(out[2]["x"], out[1]["x"])
        self.assertEqual(out[3]["x"], out[1]["x"])

    def test_follow_person_runs_forward_and_back_from_the_reference_frame(self):
        script = [[(5, (60, 40, 100, 140))]]
        result = pf.follow_person("x", 0, 0.4, BOX, at=0.2, frames=self.frames(6), model_factory=lambda: FakeModel(script))
        times = [s["t"] for s in result["samples"]]
        self.assertEqual(times, sorted(times))
        self.assertEqual(len(times), 6)


class Cache(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.old = pf.CACHE_DIR
        pf.CACHE_DIR = Path(self.dir.name)
        self.addCleanup(setattr, pf, "CACHE_DIR", self.old)
        self.video = Path(self.dir.name) / "v.mp4"
        self.video.write_bytes(b"x")
        self.old_model = pf.MODEL
        pf.MODEL = self.video
        self.addCleanup(setattr, pf, "MODEL", self.old_model)

    def frames(self, n=4):
        return [(i / 15, frame_with([((60, 40, 100, 140), WHITE)])) for i in range(n)]

    def test_a_second_run_on_the_same_stretch_does_not_run_the_detector(self):
        script = [[(5, (60, 40, 100, 140))]]
        first = pf.run_leg(iter(self.frames()), BOX, lambda: FakeModel(script), cache=pf.leg_cache(str(self.video), 0, 1, True))
        def no_detector():
            raise AssertionError("the detector ran again")
        again = pf.run_leg(iter(self.frames()), BOX, no_detector, cache=pf.leg_cache(str(self.video), 0, 1, True))
        self.assertEqual(first, again)

    def test_another_box_reuses_the_saved_people(self):
        script = [[(5, (60, 40, 100, 140)), (6, (200, 40, 240, 140))]]
        pf.run_leg(iter(self.frames()), BOX, lambda: FakeModel(script), cache=pf.leg_cache(str(self.video), 0, 1, True))
        other = {"x": 0.62, "y": 0.2, "w": 0.15, "h": 0.5}
        def no_detector():
            raise AssertionError("the detector ran again")
        out = pf.run_leg(iter(self.frames()), other, no_detector, cache=pf.leg_cache(str(self.video), 0, 1, True))
        self.assertEqual(len(out), 4)

    def test_a_different_stretch_or_direction_is_not_confused(self):
        script = [[(5, (60, 40, 100, 140))]]
        pf.run_leg(iter(self.frames()), BOX, lambda: FakeModel(script), cache=pf.leg_cache(str(self.video), 0, 1, True))
        self.assertIsNone(pf.leg_cache(str(self.video), 0, 2, True)[0]())
        self.assertIsNone(pf.leg_cache(str(self.video), 0, 1, False)[0]())

    def test_a_leg_that_never_finished_is_not_saved(self):
        with self.assertRaises(pf.NoPerson):
            pf.run_leg(iter(self.frames()), BOX, lambda: FakeModel([[(1, (250, 10, 300, 150))]]), cache=pf.leg_cache(str(self.video), 0, 1, True))
        self.assertIsNone(pf.leg_cache(str(self.video), 0, 1, True)[0]())

    def test_no_cache_folder_means_no_cache(self):
        pf.CACHE_DIR = None
        self.assertIsNone(pf.leg_cache(str(self.video), 0, 1, True))

    def test_only_the_newest_legs_are_kept(self):
        import os
        for n in range(5):
            f = Path(self.dir.name) / f"{n}.json"
            f.write_text("[]")
            os.utime(f, (n, n))
        pf.prune(Path(self.dir.name), keep=2)
        self.assertEqual(sorted(f.name for f in Path(self.dir.name).glob("*.json")), ["3.json", "4.json"])

    def test_progress_counts_every_frame(self):
        seen = []
        script = [[(5, (60, 40, 100, 140))]]
        pf.follow_person("x", 0, 0.4, BOX, at=0.2, frames=self.frames(6), model_factory=lambda: FakeModel(script),
                         progress=lambda done, total: seen.append((done, total)))
        self.assertEqual({total for _, total in seen}, {6})
        self.assertEqual([d for d, _ in seen], sorted(d for d, _ in seen))


if __name__ == "__main__":
    unittest.main()
