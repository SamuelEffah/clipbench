import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import speaker_follow as sf

FPS = sf.FPS


def times(n, start=0.0):
    return [round(start + i / FPS, 2) for i in range(n)]


def track(tid, moves, x=0.3, y=0.4):
    return {"id": tid, "samples": [{"t": t, "x": x, "y": y, "w": 0.1, "h": 0.1, "move": m} for t, m in zip(times(len(moves)), moves)]}


class FakeDetector:
    """Two faces side by side whose mouths are drawn into the frame: the left one at (40, 50), the right one at (160, 50)."""
    def setInputSize(self, size):
        pass

    def detect(self, frame):
        rows = []
        for cx in (40, 160):
            rows.append([cx - 15, 30, 30, 40, 0, 0, 0, 0, 0, 0, cx - 8, 60, cx + 8, 60, 0.99])
        return 1, np.array(rows, np.float32)


def scene(n, speaker_of):
    rng = np.random.default_rng(1)
    out = []
    for i in range(n):
        frame = np.full((100, 200, 3), 90, np.uint8)
        who = speaker_of(i)
        if who is not None:
            cx = 40 if who == 0 else 160
            frame[55:66, cx - 11:cx + 11] = rng.integers(0, 255, (11, 22, 1), dtype=np.uint8)
        out.append((round(i / FPS, 2), frame))
    return out


class CutDetector:
    """Shot 1 (frame value 90) has two faces, shot 2 (frame value 200) a close-up of one face in the middle."""
    def setInputSize(self, size):
        pass

    def detect(self, frame):
        if int(frame[0, 0, 0]) == 90:
            return FakeDetector().detect(frame)
        return 1, np.array([[85, 20, 30, 40, 0, 0, 0, 0, 0, 0, 92, 50, 108, 50, 0.99]], np.float32)


def two_shots(first, total):
    rng = np.random.default_rng(2)
    out = []
    for i in range(total):
        shot = 90 if i < first else 200
        frame = np.full((100, 200, 3), shot, np.uint8)
        if shot == 90 and i % 2 == 0:
            frame[55:66, 29:51] = rng.integers(0, 255, (11, 22, 1), dtype=np.uint8)
        if shot == 200:
            frame[45:56, 89:111] = rng.integers(0, 255, (11, 22, 1), dtype=np.uint8)
        out.append((round(i / FPS, 2), frame))
    return out


class SpeakerTests(unittest.TestCase):
    def test_shots_are_split_at_the_cuts(self):
        self.assertEqual(sf.shot_bounds(times(10), [0.4, 0.7]), [(0, 3), (4, 6), (7, 9)])
        self.assertEqual(sf.shot_bounds(times(5), []), [(0, 4)])

    def test_a_cut_sends_the_crop_to_the_new_shot_at_once(self):
        frames = two_shots(40, 80)
        cut = lambda a, b: int(a[0, 0, 0]) != int(b[0, 0, 0])
        out = sf.follow_speaker("x.mp4", 0.0, 8.0, frames=frames, detector=CutDetector(), talking=[True] * 80, is_cut=cut)
        self.assertTrue(out["found"])
        at = lambda t: min(out["track"], key=lambda k: abs(k["t"] - t))["x"]
        self.assertAlmostEqual(at(2.0), 0.2, places=1)
        self.assertAlmostEqual(at(4.05), 0.5, places=1)
        self.assertAlmostEqual(at(6.0), 0.5, places=1)

    def test_a_shot_where_nobody_clearly_talks_follows_the_face_on_screen(self):
        frames = two_shots(40, 80)
        cut = lambda a, b: int(a[0, 0, 0]) != int(b[0, 0, 0])
        talking = [True] * 40 + [False] * 40
        out = sf.follow_speaker("x.mp4", 0.0, 8.0, frames=frames, detector=CutDetector(), talking=talking, is_cut=cut)
        at = lambda t: min(out["track"], key=lambda k: abs(k["t"] - t))["x"]
        self.assertAlmostEqual(at(6.0), 0.5, places=1)

    def test_words_become_speech_flags_with_a_little_padding(self):
        flags = sf.speech_flags(times(10), [["hi", 0.2, 0.4]], 0.0)
        self.assertEqual([t for t, f in zip(times(10), flags) if f], [0.1, 0.2, 0.3, 0.4, 0.5])

    def test_the_face_that_moves_wins_while_someone_talks(self):
        tracks = [track(0, [0.02] * 20), track(1, [0.0] * 20)]
        who = sf.winners(tracks, times(20), [True] * 20)
        self.assertEqual(set(who[3:17]), {0})

    def test_nobody_wins_in_silence_or_without_a_clear_lead(self):
        tracks = [track(0, [0.02] * 20), track(1, [0.019] * 20)]
        self.assertEqual(set(sf.winners(tracks, times(20), [True] * 20)), {None})
        self.assertEqual(set(sf.winners([track(0, [0.05] * 20)], times(20), [False] * 20)), {None})

    def test_a_still_mouth_is_not_a_speaker(self):
        self.assertEqual(set(sf.winners([track(0, [0.001] * 20)], times(20), [True] * 20)), {None})

    def test_a_short_interruption_does_not_move_the_crop(self):
        who = [0] * 20 + [1] * 4 + [0] * 20
        spans = sf.segments(times(44), who)
        self.assertEqual([s[2] for s in spans], [0])

    def test_a_new_speaker_takes_over_after_the_hold(self):
        who = [0] * 20 + [1] * 20
        spans = sf.segments(times(40), who)
        self.assertEqual([s[2] for s in spans], [0, 1])
        self.assertAlmostEqual(spans[0][1], 2.0, places=1)
        self.assertEqual(spans[0][1], spans[1][0])

    def test_silence_between_turns_keeps_the_last_speaker(self):
        who = [0] * 10 + [None] * 10 + [0] * 10
        self.assertEqual([s[2] for s in sf.segments(times(30), who)], [0])

    def test_no_speaker_means_no_spans(self):
        self.assertEqual(sf.segments(times(10), [None] * 10), [])

    def test_the_crop_jumps_to_the_new_speaker_over_the_ramp(self):
        tracks = [track(0, [0.02] * 40, x=0.25), track(1, [0.02] * 40, x=0.75)]
        keys = sf.crop_track(tracks, [[0.0, 2.0, 0], [2.0, 3.9, 1]])
        at = {k["t"]: k["x"] for k in keys}
        self.assertEqual(at[2.0], 0.25)
        self.assertEqual(at[round(2.0 + sf.RAMP, 2)], 0.75)
        self.assertEqual([k["t"] for k in keys], sorted(k["t"] for k in keys))

    def test_a_face_keeps_its_identity_between_looks(self):
        gray = np.zeros((100, 200), np.uint8)
        face = {"box": (25.0, 30.0, 30.0, 40.0), "mouth": (40.0, 60.0, 20.0, 12.0)}
        near = {"box": (27.0, 30.0, 30.0, 40.0), "mouth": (42.0, 60.0, 20.0, 12.0)}
        tracks = sf.link([], [face], 0.0, 200, 100, gray)
        sf.link(tracks, [near], 0.1, 200, 100, gray)
        self.assertEqual((len(tracks), len(tracks[0]["samples"])), (1, 2))

    def test_a_second_face_starts_its_own_track(self):
        gray = np.zeros((100, 200), np.uint8)
        a = {"box": (25.0, 30.0, 30.0, 40.0), "mouth": (40.0, 60.0, 20.0, 12.0)}
        b = {"box": (145.0, 30.0, 30.0, 40.0), "mouth": (160.0, 60.0, 20.0, 12.0)}
        self.assertEqual(len(sf.link([], [a, b], 0.0, 200, 100, gray)), 2)

    def test_it_follows_the_talker_from_the_left_face_to_the_right(self):
        frames = scene(60, lambda i: 0 if i < 30 else 1)
        out = sf.follow_speaker("x.mp4", 0.0, 6.0, frames=frames, detector=FakeDetector(), talking=[True] * 60)
        self.assertTrue(out["found"])
        track_x = [k["x"] for k in out["track"]]
        self.assertAlmostEqual(track_x[0], 0.2, places=2)
        self.assertAlmostEqual(track_x[-1], 0.8, places=2)
        self.assertEqual([s["id"] for s in out["speakers"]], [0, 1])

    def test_a_silent_clip_has_no_speaker(self):
        frames = scene(30, lambda i: 0)
        out = sf.follow_speaker("x.mp4", 0.0, 3.0, frames=frames, detector=FakeDetector(), talking=[False] * 30)
        self.assertFalse(out["found"])

    def test_long_stretches_are_refused(self):
        with self.assertRaises(ValueError):
            sf.follow_speaker("x.mp4", 0.0, 500.0, frames=[], detector=FakeDetector(), talking=[])


if __name__ == "__main__":
    unittest.main()
