import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import clip_moments  # noqa: E402
import suggest  # noqa: E402

PER = 20


def track(duration, loud=(), base=20):
    """Peaks at PER a second, quiet except for the (start, end) stretches in `loud`."""
    pk = [base] * int(duration * PER)
    for a, b in loud:
        for i in range(int(a * PER), int(b * PER)):
            pk[i] = 230
    return pk


class Windows(unittest.TestCase):
    def test_the_loud_stretch_is_offered(self):
        found = clip_moments.windows(120, [], track(120, [(60, 80)]), PER)
        self.assertTrue(any(w["in"] <= 62 and w["out"] >= 78 for w in found))

    def test_every_window_is_within_the_length_limits_and_the_video(self):
        for w in clip_moments.windows(90, [], track(90, [(10, 30), (50, 70)]), PER):
            self.assertGreaterEqual(w["out"] - w["in"], suggest.MIN_LEN)
            self.assertLessEqual(w["out"] - w["in"], suggest.MAX_LEN + 2)
            self.assertGreaterEqual(w["in"], 0)
            self.assertLessEqual(w["out"], 90)

    def test_edges_snap_to_nearby_scene_cuts(self):
        found = clip_moments.windows(120, [59.2, 80.6], track(120, [(60, 80)]), PER)
        best = min(found, key=lambda w: abs(w["in"] - 59.2) + abs(w["out"] - 80.6))
        self.assertAlmostEqual(best["in"], 59.2, places=1)
        self.assertAlmostEqual(best["out"], 80.6, places=1)

    def test_a_short_video_gets_one_whole_window(self):
        found = clip_moments.windows(12, [], track(12), PER)
        self.assertEqual([(w["in"], w["out"]) for w in found], [(0.0, 12.0)])

    def test_a_video_too_short_or_silent_gives_nothing(self):
        self.assertEqual(clip_moments.windows(5, [], track(5), PER), [])
        self.assertEqual(clip_moments.windows(60, [], [], PER), [])

    def test_spoken_lines_inside_a_window_become_its_text(self):
        cues = [(61.0, 64.0, "Hold on."), (200.0, 203.0, "Far away.")]
        found = clip_moments.windows(120, [], track(120, [(60, 80)]), PER, cues)
        hit = next(w for w in found if w["in"] <= 61 and w["out"] >= 64)
        self.assertEqual(hit["text"], "Hold on.")
        self.assertEqual(next(w for w in found if w["out"] < 50)["text"], "")


class Shots(unittest.TestCase):
    def test_a_whole_shot_between_cuts_is_offered(self):
        found = clip_moments.windows(80, [19.0, 41.0, 67.0], track(80, [(42, 66)]), PER)
        self.assertIn((41.0, 67.0), [(w["in"], w["out"]) for w in found])

    def test_sustained_loud_beats_a_quiet_stretch_with_one_peak_in_the_ranking(self):
        peaks = track(80, [(42, 66)])
        for i in range(int(30 * PER), int(31 * PER)):
            peaks[i] = 255
        got = suggest.suggest([], 80, [19.0, 41.0, 67.0], peaks, PER)
        self.assertGreaterEqual(min(got[0]["out"], 66) - max(got[0]["in"], 42), 18)


class SpeechlessSuggest(unittest.TestCase):
    def test_a_speechless_video_gets_clips_from_its_sound(self):
        peaks = track(120, [(30, 50), (90, 105)])
        got = suggest.suggest([], 120, [], peaks, PER)
        self.assertGreaterEqual(len(got), 2)
        for clip in got:
            self.assertEqual(clip["text"], "")
        for loud in ((30, 50), (90, 105)):
            self.assertTrue(any(min(c["out"], loud[1]) - max(c["in"], loud[0]) >= 4 for c in got))

    def test_a_talking_video_does_not_get_sound_only_windows(self):
        cues = [(i * 6.0, i * 6.0 + 5.0, f"Line number {i} is said here.") for i in range(20)]
        got = suggest.suggest(cues, 120, [], track(120, [(30, 50)]), PER, profile={"kind": "speech", "speech": 0.8, "cuts": 0, "pace": 150})
        self.assertTrue(all(c["text"] for c in got))

    def test_the_model_is_not_asked_about_speechless_windows(self):
        asked = []
        original = suggest.llm_scores
        suggest.llm_scores = lambda items, model, progress=None: asked.append(items) or {}
        try:
            suggest.suggest([], 120, [], track(120, [(30, 50)]), PER, model="m")
        finally:
            suggest.llm_scores = original
        self.assertEqual(asked, [])


if __name__ == "__main__":
    unittest.main()
