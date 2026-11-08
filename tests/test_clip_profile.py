import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import clip_profile  # noqa: E402


def talking(n, per_sec=20):
    """Loudness of speech: bursts with pauses between them."""
    return ([200] * per_sec + [10] * per_sec) * (n // (2 * per_sec) + 1)


def talk(duration, per_min_words=150):
    """Back-to-back lines covering the whole video."""
    cues, t = [], 0.0
    words = max(1, round(per_min_words / 60 * 4))
    while t + 4 <= duration:
        cues.append((t, t + 4, " ".join(["word"] * words)))
        t += 4
    return cues


class Profile(unittest.TestCase):
    def test_sound_that_never_pauses_is_steady_and_so_not_speech_even_with_sung_words(self):
        got = clip_profile.profile(talk(300), 300, [], [180, 200, 170, 190] * 1500, 20)
        self.assertTrue(got["steady"])
        self.assertEqual(got["kind"], "audio")

    def test_talk_with_pauses_is_not_steady(self):
        self.assertFalse(clip_profile.profile(talk(300), 300, [], talking(6000)[:6000], 20)["steady"])

    def test_steady_with_many_cuts_is_visual(self):
        cuts = [i * 4.0 for i in range(1, 75)]
        self.assertEqual(clip_profile.profile([], 300, cuts, [180, 200] * 3000, 20)["kind"], "visual")


    def test_a_video_full_of_dialogue_is_speech(self):
        got = clip_profile.profile(talk(300), 300, [], talking(6000)[:6000], 20)
        self.assertEqual(got["kind"], "speech")
        self.assertGreater(got["speech"], 0.9)

    def test_little_speech_and_many_cuts_is_visual(self):
        cues = [(10, 12, "hey")]
        cuts = [i * 4.0 for i in range(1, 75)]
        got = clip_profile.profile(cues, 300, cuts, talking(6000)[:6000], 20)
        self.assertEqual(got["kind"], "visual")
        self.assertGreater(got["cuts"], 10)

    def test_little_speech_and_few_cuts_is_audio(self):
        got = clip_profile.profile([(10, 12, "hey")], 300, [], talking(6000)[:6000], 20)
        self.assertEqual(got["kind"], "audio")

    def test_in_between_is_mixed(self):
        cues = [(i * 10.0, i * 10.0 + 4, "a few words here") for i in range(30)]
        got = clip_profile.profile(cues, 300, [], talking(6000)[:6000], 20)
        self.assertEqual(got["kind"], "mixed")

    def test_empty_input_does_not_crash(self):
        got = clip_profile.profile([], 0, [], [], 20)
        self.assertEqual(got["kind"], "audio")
        self.assertEqual(got["speech"], 0)


class Weights(unittest.TestCase):
    def test_speech_leans_on_wording_and_visual_on_energy(self):
        speech = clip_profile.weights({"kind": "speech"})
        visual = clip_profile.weights({"kind": "visual"})
        self.assertGreater(speech["wording"], speech["energy"])
        self.assertGreater(visual["energy"], visual["wording"])

    def test_every_kind_has_positive_weights(self):
        for kind in ("speech", "visual", "audio", "mixed", "unknown"):
            w = clip_profile.weights({"kind": kind})
            self.assertTrue(all(w[k] > 0 for k in ("energy", "wording", "hook")), kind)


if __name__ == "__main__":
    unittest.main()
