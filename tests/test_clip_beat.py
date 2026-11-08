import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import clip_beat  # noqa: E402
import clip_moments  # noqa: E402

PER = 20


def kicks(seconds, every=0.5):
    """Quiet bed with a loud hit every `every` seconds."""
    pk = [60] * int(seconds * PER)
    for i in range(int(every * PER), len(pk), int(every * PER)):
        pk[i] = 240
    return pk


class Onsets(unittest.TestCase):
    def test_hits_are_found_where_they_land(self):
        got = clip_beat.onsets(kicks(10), PER)
        self.assertEqual(got[:3], [0.5, 1.0, 1.5])

    def test_a_flat_track_has_none(self):
        self.assertEqual(clip_beat.onsets([100] * 400, PER), [])

    def test_too_little_audio_has_none(self):
        self.assertEqual(clip_beat.onsets([], PER), [])
        self.assertEqual(clip_beat.onsets([5, 9], PER), [])


class SnapToBeats(unittest.TestCase):
    def test_edges_land_on_a_beat_when_there_is_no_cut(self):
        peaks = kicks(120, 1.0)
        beats = clip_beat.onsets(peaks, PER)
        found = clip_moments.windows(120, [], peaks, PER, beats=beats)
        self.assertTrue(found)
        for w in found:
            self.assertTrue(w["in"] == 0 or any(abs(w["in"] - b) < 0.01 for b in beats))

    def test_a_scene_cut_still_wins_over_a_beat(self):
        peaks = kicks(120, 1.0)
        found = clip_moments.windows(120, [30.3], peaks, PER, beats=clip_beat.onsets(peaks, PER))
        self.assertTrue(all(w["in"] != 30.0 for w in found))


if __name__ == "__main__":
    unittest.main()
