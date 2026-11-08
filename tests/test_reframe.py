import sys
import unittest
import unittest.mock
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import reframe


def frames(n, h=270, w=480):
    return [(float(t), np.zeros((h, w), np.uint8)) for t in range(n)]


class ReframeTests(unittest.TestCase):
    def test_largest_face_wins(self):
        self.assertEqual(reframe.largest([(0, 0, 10, 10), (50, 50, 40, 30), (5, 5, 20, 20)]), (50, 50, 40, 30))
        self.assertIsNone(reframe.largest([]))

    def test_a_detection_is_stored_as_fractions_of_the_frame(self):
        s = reframe.sample_of(2.0, (96, 54, 96, 54), 480, 270)
        self.assertEqual((s["x"], s["y"], s["w"], s["h"]), (0.3, 0.3, 0.2, 0.2))

    def test_the_median_face_ignores_one_stray_detection(self):
        samples = [{"t": i, "x": 0.5, "y": 0.4, "w": 0.2, "h": 0.2} for i in range(4)] + [{"t": 4, "x": 0.9, "y": 0.9, "w": 0.1, "h": 0.1}]
        face = reframe.summarize(samples, 5)
        self.assertEqual((face["x"], face["y"], face["w"]), (0.5, 0.4, 0.2))

    def test_too_few_hits_means_no_face(self):
        self.assertIsNone(reframe.summarize([], 5))
        self.assertIsNone(reframe.summarize([{"t": 0, "x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2}], 10))

    def test_find_faces_reads_the_biggest_face_in_each_frame(self):
        detect = lambda gray: [(10, 10, 20, 20), (200, 100, 80, 60)]
        out = reframe.find_faces("x.mp4", 0, 3, frames=frames(3), detector=detect)
        self.assertTrue(out["found"])
        self.assertEqual((out["looked"], len(out["samples"])), (3, 3))
        self.assertAlmostEqual(out["face"]["x"], 240 / 480, places=3)

    def test_a_clip_with_no_face_is_reported_not_guessed(self):
        out = reframe.find_faces("x.mp4", 0, 3, frames=frames(3), detector=lambda gray: [])
        self.assertEqual((out["found"], out["face"], out["samples"]), (False, None, []))

    def test_bad_ranges_are_refused(self):
        for a, b in ((5, 5), (-1, 3), (0, 9999)):
            with self.assertRaises(ValueError):
                reframe.find_faces("x.mp4", a, b, frames=[], detector=lambda g: [])

    def test_long_clips_are_thinned_to_the_sample_cap(self):
        self.assertEqual(reframe.sample_step(30), 1.0)
        self.assertLessEqual(reframe.MAX_SPAN / reframe.sample_step(reframe.MAX_SPAN), reframe.MAX_SAMPLES)


class AnimeCascadeTests(unittest.TestCase):
    def test_the_anime_model_ships_and_loads(self):
        import cv2
        self.assertTrue(reframe.ANIME_CASCADE.is_file())
        self.assertFalse(cv2.CascadeClassifier(str(reframe.ANIME_CASCADE)).empty())

    def test_the_anime_model_is_tried_before_the_human_one(self):
        import cv2
        loaded = []
        real = cv2.CascadeClassifier

        def spy(path):
            loaded.append(Path(path).name)
            return real(path)
        with unittest.mock.patch("cv2.CascadeClassifier", spy):
            reframe.cascade_detector()
        self.assertEqual(loaded, ["lbpcascade_animeface.xml", "haarcascade_frontalface_default.xml"])


if __name__ == "__main__":
    unittest.main()


class FollowTests(unittest.TestCase):
    class Stub:
        """A tracker that reports the box moving 10 pixels right per frame."""
        def __init__(self, box):
            self.box = list(box)

        def update(self, gray):
            self.box[0] += 10
            return True, tuple(self.box)

    class Loses(Stub):
        def update(self, gray):
            return False, (0, 0, 0, 0)

    def test_the_subject_is_followed_frame_by_frame(self):
        box = {"x": 0.2, "y": 0.4, "w": 0.1, "h": 0.2}
        out = reframe.follow_subject("x.mp4", 0, 3, box, frames=frames(3), make_tracker=lambda g, b: self.Stub(b))
        xs = [s["x"] for s in out["samples"]]
        self.assertEqual(len(xs), 3)
        self.assertAlmostEqual(xs[0], 0.25, places=3)
        self.assertGreater(xs[2], xs[1])

    def test_a_lost_subject_holds_its_last_place(self):
        box = {"x": 0.2, "y": 0.4, "w": 0.1, "h": 0.2}
        out = reframe.follow_subject("x.mp4", 0, 3, box, frames=frames(3), make_tracker=lambda g, b: self.Loses(b))
        self.assertEqual({s["x"] for s in out["samples"]}, {0.25})

    def test_a_box_outside_the_frame_is_refused(self):
        with self.assertRaises(ValueError):
            reframe.follow_subject("x.mp4", 0, 3, {"x": 0.9, "y": 0.4, "w": 0.3, "h": 0.2}, frames=frames(3))

    def test_the_sampling_step_gives_a_quarter_second_for_short_clips_and_thins_long_ones(self):
        self.assertEqual(reframe.follow_step(10), 0.25)
        self.assertAlmostEqual(reframe.follow_step(100), 1.0)


class FollowFromAnyFrameTests(unittest.TestCase):
    class Walker:
        """Moves the box 10 pixels right on every frame it is handed."""
        def __init__(self, box):
            self.box = list(box)

        def update(self, gray):
            self.box[0] += 10
            return True, tuple(self.box)

    box = {"x": 0.5, "y": 0.4, "w": 0.1, "h": 0.2}

    def track_at(self, at):
        return reframe.follow_subject("x.mp4", 0, 6, self.box, frames=frames(7), make_tracker=lambda g, b: self.Walker(b), at=at)["samples"]

    def test_samples_cover_the_whole_clip_in_time_order(self):
        samples = self.track_at(3.0)
        self.assertEqual([s["t"] for s in samples], [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0])

    def test_the_reference_frame_sits_on_the_box(self):
        samples = self.track_at(3.0)
        self.assertAlmostEqual(samples[3]["x"], 0.55, places=3)

    def test_each_direction_is_tracked_away_from_the_reference_frame(self):
        samples = self.track_at(3.0)
        step = 10 / 480
        self.assertAlmostEqual(samples[4]["x"] - samples[3]["x"], step, places=3)
        self.assertAlmostEqual(samples[2]["x"] - samples[3]["x"], step, places=3)
        self.assertAlmostEqual(samples[0]["x"] - samples[3]["x"], 3 * step, places=3)

    def test_a_reference_time_outside_the_clip_is_refused(self):
        with self.assertRaises(ValueError):
            self.track_at(9.0)

    def test_a_lost_subject_is_found_again_by_matching_its_look(self):
        import cv2
        gray = np.zeros((270, 480), np.uint8)
        cv2.circle(gray, (300, 140), 20, 255, -1)
        cv2.circle(gray, (300, 140), 8, 90, -1)
        found = reframe.rematch(gray, (90, 90, 40, 40), gray[120:160, 280:320], 0.6)
        self.assertIsNotNone(found)
        self.assertAlmostEqual(found[0], 280, delta=3)
        self.assertIsNone(reframe.rematch(np.zeros((270, 480), np.uint8), (90, 90, 40, 40), gray[120:160, 280:320], 0.6))


class FaceDetectorAvailabilityTests(unittest.TestCase):
    def test_an_opencv_without_cascades_fails_with_the_setup_hint(self):
        import types
        bare = types.SimpleNamespace(data=types.SimpleNamespace(haarcascades=""))
        with unittest.mock.patch.dict(sys.modules, {"cv2": bare}):
            with self.assertRaises(reframe.NoFaceDetector) as caught:
                reframe.cascade_detector()
        self.assertIn("./setup.sh", str(caught.exception))
        self.assertIsInstance(caught.exception, ImportError)
