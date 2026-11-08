import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import auto_layout as al

W, H = 320, 180


def row(x, y, w, h):
    """A YuNet row for a face box: x, y, w, h, five landmarks, score."""
    return [x, y, w, h, x + w * 0.3, y + h * 0.4, x + w * 0.7, y + h * 0.4, 0, 0, x + w * 0.35, y + h * 0.75, x + w * 0.65, y + h * 0.75, 0.99]


class Detector:
    """Reports the same boxes on every frame, or the boxes `per_frame` gives for the frame's brightness."""
    def __init__(self, boxes, per_frame=None):
        self.boxes, self.per_frame = boxes, per_frame

    def setInputSize(self, size):
        pass

    def detect(self, frame):
        boxes = self.per_frame(int(frame[0, 0, 0])) if self.per_frame else self.boxes
        return 1, (np.array([row(*b) for b in boxes], np.float32) if boxes else None)


def clip(n=8, value=90):
    return [(i * 0.5, np.full((H, W, 3), value, np.uint8)) for i in range(n)]


def run(boxes, n=8, per_frame=None, frames=None, remembered=None):
    return al.analyze("x.mp4", 0, n * 0.5, frames=frames or clip(n), detector=Detector(boxes, per_frame), is_cut=lambda a, b: False, remembered=remembered)


def game_with_cam(left=True, bottom=True):
    """Coarse random 'gameplay' with a flat webcam block in a corner: 30% of the width, 40% of the height."""
    rng = np.random.default_rng(3)
    base = np.kron(rng.integers(0, 60, (H // 20, W // 20), dtype=np.uint8), np.ones((20, 20), np.uint8))
    cw, ch = int(W * 0.3), int(H * 0.4)
    x0, y0 = (0 if left else W - cw), (H - ch if bottom else 0)
    base[y0:y0 + ch, x0:x0 + cw] = 128
    frame = np.dstack([base] * 3)
    return [(i * 0.5, frame.copy()) for i in range(8)]


def game_with_side_cam(left=True, top=0.3, height=0.2, width=0.21, moving=False, inner_line=None, faint_line=None, waving=False):
    """Soft random 'gameplay' (no hard edges of its own) with a flat webcam block against one side edge at mid height, the way a streamer parks it beside the game.

    `moving` re-rolls the gameplay every frame while the webcam holds still; `inner_line` draws a dark vertical line at that column inside the webcam, like a chair's edge;
    `faint_line` draws a fainter one at that column in the game beyond the webcam; `waving` flickers a patch inside the webcam every frame, like a streamer's hands.
    """
    rng = np.random.default_rng(5)
    cw, ch, y0 = int(W * width), int(H * height), int(H * top)
    x0 = 0 if left else W - cw
    frames = []
    for i in range(8):
        if not frames or moving:
            base = np.kron(rng.integers(0, 19, (H // 20, W // 20), dtype=np.uint8), np.ones((20, 20), np.uint8))
            base[y0:y0 + ch, x0:x0 + cw] = 128
            if inner_line is not None:
                base[y0:y0 + ch, inner_line:inner_line + 2] = 0
            if faint_line is not None:
                base[y0:y0 + ch, faint_line:faint_line + 2] = 45
        frame = base.copy()
        if waving:
            frame[y0 + 4:y0 + ch - 4, x0 + 4:x0 + cw - 4] = 128 if i % 2 else 200
        frames.append((i * 0.5, np.dstack([frame] * 3)))
    return frames


class AlreadyVertical(unittest.TestCase):
    def test_a_portrait_video_stays_whole_even_with_a_face_in_it(self):
        tall = [(i * 0.5, np.full((320, 180, 3), 90, np.uint8)) for i in range(8)]
        found = al.analyze("x.mp4", 0, 4, frames=tall, detector=Detector([(40, 60, 60, 80)]), is_cut=lambda a, b: False)
        self.assertEqual(found["layout"], "none")
        self.assertIn("vertical", found["reason"])
        self.assertEqual([(s["start"], s["end"], s["layout"]) for s in found["segments"]], [(0, 4, "none")])


def two_blocks():
    """Gameplay with a small flat webcam block bottom-left and a big flat panel top-right, each with a steady face in it."""
    rng = np.random.default_rng(3)
    base = np.kron(rng.integers(0, 60, (H // 20, W // 20), dtype=np.uint8), np.ones((20, 20), np.uint8))
    base[int(H * 0.6):, :int(W * 0.3)] = 128
    base[:int(H * 0.49), int(W * 0.52):] = 200
    frame = np.dstack([base] * 3)
    return [(i * 0.5, frame.copy()) for i in range(8)]


class TwoFramedFaces(unittest.TestCase):
    def test_the_smaller_framed_rectangle_is_the_webcam_not_the_big_panel(self):
        found = run([(255, 15, 40, 50), (30, 120, 30, 40)], frames=two_blocks())
        self.assertEqual(found["layout"], "webcam", found["reason"])
        self.assertLess(found["webcam"]["w"], 0.35)
        self.assertGreater(found["webcam"]["y"], 0.5)


def faint_corner_cam(panel_until=0):
    """A dark menu screen with a corner webcam only a shade brighter than it, so its border barely shows; `panel_until` frames also carry a bright panel top-right."""
    frames = []
    for i in range(8):
        base = np.full((H, W), 60, np.uint8)
        base[int(H * 0.6):, :int(W * 0.3)] = 72
        if i < panel_until:
            base[:int(H * 0.49), int(W * 0.52):] = 200
        frame = np.dstack([base] * 3)
        frame[0, 0, :] = i
        frames.append((i * 0.5, frame))
    return frames


class FaintCornerCam(unittest.TestCase):
    def test_a_steady_corner_face_without_a_visible_border_is_still_a_cam_sized_from_the_face_and_marked_guessed(self):
        found = run([(30, 120, 30, 40)], frames=faint_corner_cam())
        self.assertEqual(found["layout"], "webcam", found["reason"])
        self.assertTrue(found["guessed"])
        cam = found["webcam"]
        self.assertEqual(cam["x"], 0.0)
        self.assertGreater(cam["y"], 0.4)
        self.assertLess(cam["w"], 0.35)

    def test_a_cam_found_from_its_border_is_not_marked_guessed(self):
        self.assertFalse(run([(30, 120, 30, 40)], frames=game_with_cam())["guessed"])

    def test_a_corner_face_seen_throughout_beats_a_framed_face_that_comes_and_goes(self):
        boxes = lambda v: [(255, 15, 40, 50), (30, 120, 30, 40)] if v < 5 else [(30, 120, 30, 40)]
        found = run(None, per_frame=boxes, frames=faint_corner_cam(panel_until=5))
        self.assertEqual(found["layout"], "webcam", found["reason"])
        self.assertEqual(found["webcam"]["x"], 0.0)
        self.assertGreater(found["webcam"]["y"], 0.4)
        self.assertTrue(found["guessed"])


REMEMBERED = {"x": 0.0, "y": 0.6, "w": 0.3, "h": 0.4}


class RememberedCam(unittest.TestCase):
    def test_the_streams_cam_is_kept_when_nobody_is_in_it_but_its_border_still_shows(self):
        found = run([], frames=game_with_cam(), remembered=REMEMBERED)
        self.assertEqual(found["layout"], "webcam", found["reason"])
        self.assertEqual(found["webcam"], REMEMBERED)
        self.assertTrue(found["remembered"])
        self.assertEqual(found["faces"], [])
        self.assertEqual([(s["start"], s["end"]) for s in found["segments"]], [(0, 4)])

    def test_a_remembered_cam_whose_border_is_gone_is_not_used(self):
        self.assertEqual(run([], remembered=REMEMBERED)["layout"], "none")

    def test_a_remembered_cam_beats_a_face_in_the_game(self):
        found = run([(180, 30, 90, 110)], frames=game_with_cam(), remembered=REMEMBERED)
        self.assertEqual(found["layout"], "webcam", found["reason"])
        self.assertEqual(found["webcam"], REMEMBERED)

    def test_a_cam_only_guessed_from_its_face_takes_the_remembered_one_around_that_face(self):
        found = run([(30, 120, 30, 40)], frames=faint_corner_cam(), remembered=REMEMBERED)
        self.assertEqual(found["webcam"], REMEMBERED)
        self.assertFalse(found["guessed"])

    def test_a_cam_found_from_its_border_snaps_to_the_remembered_one_when_they_all_but_coincide(self):
        close = {"x": 0.0, "y": 0.58, "w": 0.3, "h": 0.42}
        found = run([(30, 120, 30, 40)], frames=game_with_cam(), remembered=close)
        self.assertEqual(found["webcam"], close)
        self.assertFalse(found["guessed"])

    def test_a_corner_face_with_no_border_at_all_takes_the_remembered_cam_around_it(self):
        found = run([(30, 120, 30, 40)], remembered=REMEMBERED)
        self.assertEqual(found["layout"], "webcam", found["reason"])
        self.assertEqual(found["webcam"], REMEMBERED)

    def test_shots_of_one_cam_are_one_stretch_whether_or_not_someone_is_in_it(self):
        with_face = {"layout": "webcam", "faces": [{"x": 0.1, "y": 0.8, "w": 0.1, "h": 0.2}], "webcam": {"x": 0.05, "y": 0.59, "w": 0.17, "h": 0.41}, "start": 0}
        empty = {"layout": "webcam", "faces": [], "webcam": REMEMBERED, "start": 2.5}
        self.assertEqual([(s["start"], s["end"]) for s in al.merge_segments([with_face, empty], 15)], [(0, 15)])

    def test_a_cam_found_from_its_own_border_is_not_replaced(self):
        found = run([(30, 120, 30, 40)], frames=game_with_cam(), remembered={"x": 0.0, "y": 0.5, "w": 0.4, "h": 0.5})
        self.assertNotEqual(found["webcam"]["h"], 0.5)
        self.assertFalse(found.get("remembered", False))


class HeadAtTheTopOfTheCam(unittest.TestCase):
    def test_a_streamer_whose_head_reaches_the_top_of_a_corner_cam_still_gets_it(self):
        face = {"x": 0.1087, "y": 0.6734, "w": 0.1139, "h": 0.2451}
        cam = {"x": 0.0, "y": 0.6, "w": 0.29, "h": 0.4}
        self.assertTrue(al.fits_face(cam, face, 16 / 9))

    def test_a_border_through_the_eyes_is_still_not_a_webcam(self):
        face = {"x": 0.1087, "y": 0.6734, "w": 0.1139, "h": 0.2451}
        through = {"x": 0.0, "y": 0.66, "w": 0.29, "h": 0.34}
        self.assertFalse(al.fits_face(through, face, 16 / 9))


class SideWebcam(unittest.TestCase):
    def test_a_webcam_against_the_left_edge_at_mid_height_is_found_with_both_of_its_borders(self):
        found = run([(18, 60, 24, 26)], frames=game_with_side_cam())
        self.assertEqual(found["layout"], "webcam", found["reason"])
        cam = found["webcam"]
        self.assertEqual(cam["x"], 0.0)
        self.assertAlmostEqual(cam["y"], 0.3, delta=0.03)
        self.assertAlmostEqual(cam["h"], 0.2, delta=0.03)
        self.assertAlmostEqual(cam["w"], 0.21, delta=0.03)

    def test_a_webcam_against_the_right_edge_at_mid_height_is_found_too(self):
        found = run([(W - 48, 60, 24, 26)], frames=game_with_side_cam(left=False))
        self.assertEqual(found["layout"], "webcam", found["reason"])
        cam = found["webcam"]
        self.assertAlmostEqual(cam["x"] + cam["w"], 1.0, delta=0.01)
        self.assertAlmostEqual(cam["y"], 0.3, delta=0.03)
        self.assertAlmostEqual(cam["h"], 0.2, delta=0.03)

    def test_a_side_webcam_rectangle_does_not_reach_the_top_of_the_frame(self):
        cam = run([(18, 60, 24, 26)], frames=game_with_side_cam())["webcam"]
        self.assertGreater(cam["y"], 0.2)

    def test_the_border_with_the_moving_game_outside_it_beats_a_still_edge_inside_the_webcam(self):
        cam = run([(18, 60, 24, 26)], frames=game_with_side_cam(moving=True, inner_line=58))["webcam"]
        self.assertAlmostEqual(cam["w"], 0.21, delta=0.02)

    def test_a_streamer_moving_inside_the_webcam_does_not_push_its_border_out_to_a_fainter_line_in_the_game(self):
        cam = run([(18, 60, 24, 26)], frames=game_with_side_cam(faint_line=76, waving=True))["webcam"]
        self.assertAlmostEqual(cam["w"], 0.21, delta=0.02)

    def test_the_steadiest_face_is_tried_as_the_webcam_before_a_bigger_one_that_moves(self):
        still = {"boxes": [(0.05, 0.4, 0.03, 0.06)] * 6, "frames": 6}
        moving = {"boxes": [(0.7 + i * 0.01, 0.3, 0.06, 0.12) for i in range(6)], "frames": 6}
        self.assertEqual(al.by_steadiness([moving, still]), [still, moving])

    def test_a_face_that_drifts_is_not_tried_as_a_webcam_at_all(self):
        roaming = {"boxes": [(0.1 + i * 0.03, 0.4, 0.03, 0.06) for i in range(6)], "frames": 6}
        self.assertEqual(al.by_steadiness([roaming]), [])

    def test_a_streamer_sitting_back_from_a_wide_webcam_still_gets_it(self):
        found = run([(26, 66, 8, 12)], frames=game_with_side_cam())
        self.assertEqual(found["layout"], "webcam", found["reason"])
        self.assertAlmostEqual(found["webcam"]["w"], 0.21, delta=0.03)


class Webcam(unittest.TestCase):
    def test_the_border_of_a_corner_webcam_gives_its_rectangle(self):
        cam = run([(30, 120, 30, 40)], frames=game_with_cam())["webcam"]
        self.assertAlmostEqual(cam["w"], 0.3, delta=0.03)
        self.assertAlmostEqual(cam["h"], 0.4, delta=0.03)
        self.assertEqual((cam["x"], round(cam["y"] + cam["h"], 2)), (0.0, 1.0))

    def test_a_webcam_in_the_top_right_corner_is_found_too(self):
        cam = run([(250, 15, 30, 40)], frames=game_with_cam(False, False))["webcam"]
        self.assertAlmostEqual(cam["x"] + cam["w"], 1.0, delta=0.01)
        self.assertEqual(cam["y"], 0.0)
        self.assertAlmostEqual(cam["h"], 0.4, delta=0.03)

    def test_a_face_in_the_game_does_not_turn_a_webcam_into_two_people(self):
        result = run([(30, 120, 30, 40), (250, 40, 22, 28)], frames=game_with_cam())
        self.assertEqual(result["layout"], "webcam")

    def test_a_face_without_a_border_around_it_is_not_a_webcam(self):
        noise = np.kron(np.random.default_rng(4).integers(0, 255, (H // 20, W // 20), dtype=np.uint8), np.ones((20, 20), np.uint8))
        frames = [(i * 0.5, np.dstack([noise] * 3)) for i in range(8)]
        self.assertEqual(run([(150, 70, 30, 40)], frames=frames)["layout"], "single")


def by_value(prev, frame):
    return int(prev[0, 0, 0]) != int(frame[0, 0, 0])


def shots(plan):
    """Frames at 2 a second: each (value, looks) in plan is one shot of `looks` frames filled with `value`."""
    out = []
    for value, count in plan:
        out += [(len(out) * 0.5, np.full((H, W, 3), value, np.uint8)) for _ in range(count)]
    return out


TWO = [(60, 50, 40, 50), (200, 50, 40, 50)]
ONE = [(110, 30, 90, 110)]


def cut_run(plan, boxes_by_value):
    return al.analyze("x.mp4", 0, sum(n for _, n in plan) * 0.5, frames=shots(plan),
                      detector=Detector(None, per_frame=lambda v: boxes_by_value[v]), is_cut=by_value)


class RectAroundFace(unittest.TestCase):
    def test_a_rectangle_that_ends_across_the_face_is_not_a_webcam(self):
        face = {"x": 0.394, "y": 0.411, "w": 0.1487, "h": 0.3735}
        across = {"x": 0.0, "y": 0.0, "w": 0.4953, "h": 0.4639}
        self.assertFalse(al.fits_face(across, face, 16 / 9))

    def test_a_rectangle_that_clears_the_face_still_is_one(self):
        face = {"x": 0.25, "y": 0.3, "w": 0.12, "h": 0.3}
        clear = {"x": 0.0, "y": 0.0, "w": 0.45, "h": 0.58}
        self.assertTrue(al.fits_face(clear, face, 16 / 9))

    def test_a_border_hugging_the_side_of_the_head_is_not_a_webcam(self):
        face = {"x": 0.6656, "y": 0.2557, "w": 0.1134, "h": 0.28}
        hugging = {"x": 0.5797, "y": 0.0, "w": 0.4203, "h": 0.4806}
        self.assertFalse(al.fits_face(hugging, face, 16 / 9))

    def test_a_webcam_with_room_around_the_face_on_every_side_is_kept(self):
        face = {"x": 0.85, "y": 0.25, "w": 0.1, "h": 0.2}
        around = {"x": 0.7, "y": 0.0, "w": 0.3, "h": 0.4}
        self.assertTrue(al.fits_face(around, face, 16 / 9))

    def test_the_check_holds_for_a_webcam_at_the_bottom_too(self):
        face = {"x": 0.8, "y": 0.6, "w": 0.15, "h": 0.3}
        across = {"x": 0.6, "y": 0.58, "w": 0.4, "h": 0.42}
        self.assertFalse(al.fits_face(across, face, 16 / 9))


class Shots(unittest.TestCase):
    def test_a_clip_without_cuts_is_one_segment_spanning_it(self):
        result = run(ONE)
        self.assertEqual(len(result["segments"]), 1)
        self.assertEqual((result["segments"][0]["start"], result["segments"][0]["end"]), (0, 4.0))

    def test_a_cut_to_a_different_layout_starts_a_new_segment(self):
        result = cut_run([(90, 8), (200, 8)], {90: TWO, 200: ONE})
        self.assertEqual([s["layout"] for s in result["segments"]], ["people", "single"])
        self.assertEqual([(s["start"], s["end"]) for s in result["segments"]], [(0, 4.0), (4.0, 8.0)])

    def test_a_cut_to_the_same_layout_stays_one_segment(self):
        result = cut_run([(90, 8), (200, 8)], {90: TWO, 200: TWO})
        self.assertEqual(len(result["segments"]), 1)
        self.assertEqual(result["segments"][0]["end"], 8.0)

    def test_a_shot_too_short_to_matter_joins_the_one_before(self):
        result = cut_run([(90, 8), (200, 1), (90, 8)], {90: TWO, 200: ONE})
        self.assertEqual([s["layout"] for s in result["segments"]], ["people"])

    def test_the_answer_for_the_whole_clip_is_the_longest_segment(self):
        result = cut_run([(90, 4), (200, 12)], {90: TWO, 200: ONE})
        self.assertEqual(result["layout"], "single")

    def test_each_segment_carries_its_own_faces(self):
        result = cut_run([(90, 8), (200, 8)], {90: TWO, 200: ONE})
        self.assertEqual([len(s["faces"]) for s in result["segments"]], [2, 1])


class CamAcrossCuts(unittest.TestCase):
    def two_games(self):
        a, b = game_with_cam(), game_with_cam()
        rng = np.random.default_rng(9)
        for _, frame in b:
            frame[:100, :, :] = rng.integers(0, 60, (1, 1, 3), dtype=np.uint8)
            frame[:100:20, ::20, :] = 5  # a different picture above the webcam
        return a[:8] + [(4 + t, f) for t, f in b[:8]]

    def test_a_cut_in_the_gameplay_does_not_split_a_clip_whose_webcam_stays_put(self):
        cut = lambda p, f: not np.array_equal(p[:5, :5], f[:5, :5])
        result = al.analyze("x.mp4", 0, 8, frames=self.two_games(), detector=Detector([(30, 120, 30, 40)]), is_cut=cut)
        self.assertEqual([s["layout"] for s in result["segments"]], ["webcam"])
        self.assertEqual((result["segments"][0]["start"], result["segments"][0]["end"]), (0, 8))

    def test_a_game_face_is_not_a_webcam_when_the_real_one_is_in_view(self):
        faces = lambda v: [(30, 120, 30, 40), (250, 40, 20, 26)]
        frames = self.two_games()
        result = al.analyze("x.mp4", 0, 8, frames=frames, detector=Detector(None, faces), is_cut=lambda p, f: False)
        self.assertEqual(result["webcam"]["x"], 0.0)
        self.assertGreater(result["webcam"]["y"], 0.5)

    def test_a_border_rectangle_far_bigger_than_its_face_is_not_used(self):
        cam = run([(40, 140, 6, 8)], frames=game_with_cam())["webcam"]
        self.assertLess(cam["w"], 0.1)


class StrayBorder(unittest.TestCase):
    def picture(self, block):
        rng = np.random.default_rng(3)
        base = np.kron(rng.integers(0, 60, (H // 20, W // 20), dtype=np.uint8), np.ones((20, 20), np.uint8))
        if block:
            base[108:, :144] = 128
        return np.dstack([base] * 3)

    def run_clip(self, shots):
        """`shots` is a list of (frames, has_block); a face is seen inside the flat block, only where there is one."""
        frames = []
        for count, with_block in shots:
            frames += [(len(frames) * 0.5 + i * 0.5, self.picture(with_block)) for i in range(count)]
        detector = Detector(None)
        detector.detect = lambda frame: (1, np.array([row(90, 125, 36, 40)], np.float32) if frame[130, 50, 0] == 128 else None)
        cut = lambda p, f: not np.array_equal(p, f)
        return al.analyze("x.mp4", 0, len(frames) * 0.5, frames=frames, detector=detector, is_cut=cut)

    def test_a_block_that_stays_through_the_clip_is_a_webcam(self):
        found = self.run_clip([(8, True)])
        self.assertEqual(found["layout"], "webcam")

    def test_a_block_seen_in_only_one_shot_is_not_a_webcam(self):
        found = self.run_clip([(6, True), (12, False)])
        self.assertNotIn("webcam", [s["layout"] for s in found["segments"]])


class Anchored(unittest.TestCase):
    def frames(self):
        noise = np.kron(np.random.default_rng(5).integers(0, 255, (H // 20, W // 20), dtype=np.uint8), np.ones((20, 20), np.uint8))
        return game_with_cam() + [(4 + t, np.dstack([noise] * 3)) for t, _ in game_with_cam()]

    def test_a_shot_with_no_clear_border_keeps_the_webcam_while_its_face_stays_put(self):
        cut = lambda p, f: not np.array_equal(p[:5, :5], f[:5, :5])
        found = lambda v: [(30, 120, 30, 40)]
        result = al.analyze("x.mp4", 0, 8, frames=self.frames(), detector=Detector(None, found), is_cut=cut)
        self.assertEqual([s["layout"] for s in result["segments"]], ["webcam"])

    def test_a_shot_where_the_webcam_face_is_gone_is_left_to_its_own_layout(self):
        cut = lambda p, f: not np.array_equal(p[:5, :5], f[:5, :5])
        found = lambda v: [(30, 120, 30, 40)] if v == int(self.frames()[0][1][0, 0, 0]) else [(150, 40, 80, 100)]
        result = al.analyze("x.mp4", 0, 8, frames=self.frames(), detector=Detector(None, found), is_cut=cut)
        self.assertEqual([s["layout"] for s in result["segments"]][-1], "single")


class CamShots(unittest.TestCase):
    def test_the_same_webcam_seen_in_two_shots_is_one_segment(self):
        a = {"layout": "webcam", "faces": [{"x": 0.1, "y": 0.7}], "webcam": {"x": 0.0, "y": 0.6, "w": 0.3, "h": 0.4}, "reason": "", "start": 0}
        b = {**a, "webcam": {"x": 0.0, "y": 0.62, "w": 0.29, "h": 0.38}, "start": 5}
        self.assertEqual(len(al.merge_segments([a, b], 10)), 1)

    def test_a_webcam_in_another_corner_is_a_new_segment(self):
        a = {"layout": "webcam", "faces": [{"x": 0.1, "y": 0.7}], "webcam": {"x": 0.0, "y": 0.6, "w": 0.3, "h": 0.4}, "reason": "", "start": 0}
        b = {**a, "webcam": {"x": 0.7, "y": 0.0, "w": 0.3, "h": 0.4}, "start": 5}
        self.assertEqual(len(al.merge_segments([a, b], 10)), 2)


class Classify(unittest.TestCase):
    def test_no_faces_means_none(self):
        self.assertEqual(run([])["layout"], "none")

    def test_one_big_face_is_a_single_person(self):
        result = run([(110, 30, 90, 110)])
        self.assertEqual(result["layout"], "single")
        self.assertEqual(len(result["faces"]), 1)

    def test_two_similar_faces_side_by_side_are_two_people_left_first(self):
        result = run([(200, 50, 40, 50), (60, 50, 40, 50)])
        self.assertEqual(result["layout"], "people")
        xs = [f["x"] for f in result["faces"]]
        self.assertEqual(xs, sorted(xs))
        self.assertEqual(len(xs), 2)

    def test_two_stacked_faces_are_ordered_top_first(self):
        result = run([(130, 100, 40, 50), (130, 10, 40, 50)])
        self.assertEqual(result["layout"], "people")
        ys = [f["y"] for f in result["faces"]]
        self.assertEqual(ys, sorted(ys))

    def test_a_small_steady_face_in_a_corner_is_a_webcam(self):
        result = run([(256, 8, 24, 30)])
        self.assertEqual(result["layout"], "webcam")
        cam = result["webcam"]
        self.assertGreater(cam["x"] + cam["w"], 0.9)
        self.assertLess(cam["y"], 0.05)
        self.assertGreater(cam["w"], 0.2 * 0 + 24 / W)

    def test_a_webcam_rectangle_stays_inside_the_frame(self):
        cam = run([(300, 150, 20, 26)])["webcam"]
        for edge in (cam["x"], cam["y"]):
            self.assertGreaterEqual(edge, 0)
        self.assertLessEqual(cam["x"] + cam["w"], 1.0001)
        self.assertLessEqual(cam["y"] + cam["h"], 1.0001)

    def test_a_small_face_in_the_middle_is_not_a_webcam(self):
        self.assertEqual(run([(150, 70, 20, 26)])["layout"], "single")

    def test_a_face_that_flickers_in_one_frame_is_ignored(self):
        result = run([], per_frame=lambda v: [(110, 30, 90, 110)] if v == 7 else [])
        self.assertEqual(result["layout"], "none")

    def test_a_face_that_roams_the_frame_is_not_a_webcam(self):
        spots = [(10, 8), (250, 8), (10, 140), (250, 140)]
        frames = [(i * 0.5, np.full((H, W, 3), 10 + i, np.uint8)) for i in range(8)]
        result = run([], per_frame=lambda v: [(*spots[(v - 10) % 4], 24, 30)], frames=frames)
        self.assertNotEqual(result["layout"], "webcam")

    def test_a_big_face_beats_a_tiny_one(self):
        result = run([(100, 20, 100, 130), (280, 10, 18, 22)])
        self.assertEqual(result["layout"], "single")

    def test_three_similar_faces_are_all_returned(self):
        result = run([(20, 60, 40, 50), (140, 60, 40, 50), (260, 60, 40, 50)])
        self.assertEqual(result["layout"], "people")
        self.assertEqual(len(result["faces"]), 3)

    def test_more_than_four_faces_keep_the_four_biggest(self):
        boxes = [(10 + 60 * k, 60, 30 + k, 40) for k in range(5)]
        self.assertEqual(len(run(boxes)["faces"]), 4)

    def test_faces_are_fractions_of_the_frame(self):
        face = run([(110, 30, 90, 110)])["faces"][0]
        self.assertAlmostEqual(face["x"], (110 + 45) / W, places=2)
        self.assertAlmostEqual(face["w"], 90 / W, places=2)

    def test_a_clip_too_long_is_refused(self):
        with self.assertRaises(ValueError):
            al.analyze("x.mp4", 0, al.MAX_SPAN + 1, frames=clip(), detector=Detector([]))


if __name__ == "__main__":
    unittest.main()
