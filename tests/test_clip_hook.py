import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import clip_hook  # noqa: E402

PER = 20


def item(start=10.0, end=30.0, text="What are you doing?! Stop."):
    return {"in": start, "out": end, "text": text}


def peaks(duration=60, level=40):
    return [level] * int(duration * PER)


class Opening(unittest.TestCase):
    def test_a_question_or_shout_opens_stronger_than_a_continuation(self):
        strong = clip_hook.hook(item(text="Why would anyone do that? Nobody knows."), [], peaks(), PER)
        weak = clip_hook.hook(item(text="And then because of that we went home."), [], peaks(), PER)
        self.assertGreater(strong, weak)

    def test_a_clip_that_opens_mid_thought_is_penalised(self):
        self.assertTrue(clip_hook.opens_mid_thought("but that was the point"))
        self.assertTrue(clip_hook.opens_mid_thought("...and so it began"))
        self.assertFalse(clip_hook.opens_mid_thought("Nobody expected this."))
        self.assertFalse(clip_hook.opens_mid_thought("That's so interesting, isn't it?"))

    def test_a_long_rambling_first_sentence_scores_lower(self):
        short = clip_hook.hook(item(text="Look at this. Then we talk about other things."), [], peaks(), PER)
        long = clip_hook.hook(item(text=" ".join(["word"] * 40) + ". Then more."), [], peaks(), PER)
        self.assertGreater(short, long)


class Energy(unittest.TestCase):
    def test_a_loud_start_beats_a_slow_fade_in(self):
        loud = peaks(60, 20)
        for i in range(10 * PER, 13 * PER):
            loud[i] = 240
        quiet = peaks(60, 20)
        for i in range(20 * PER, 25 * PER):
            quiet[i] = 240
        text = "Hello there."
        self.assertGreater(clip_hook.hook(item(text=text), [], loud, PER),
                           clip_hook.hook(item(text=text), [], quiet, PER))

    def test_a_cut_right_at_the_start_helps(self):
        flat = peaks()
        text = "Hello there."
        with_cut = clip_hook.hook(item(text=text), [10.2], flat, PER)
        without = clip_hook.hook(item(text=text), [25.0], flat, PER)
        self.assertGreater(with_cut, without)

    def test_scores_stay_between_zero_and_one(self):
        for pk in ([], peaks(), [255] * 2000):
            got = clip_hook.hook(item(), [10.1], pk, PER)
            self.assertTrue(0 <= got <= 1)


class Tighten(unittest.TestCase):
    def silent_then_sound(self, onset):
        pk = peaks(60, 2)
        for i in range(int(onset * PER), int((onset + 5) * PER)):
            pk[i] = 200
        return pk

    def test_dead_air_before_the_first_sound_is_trimmed(self):
        it = item(10.0, 30.0)
        cues = [(12.5, 15.0, "Finally something.")]
        got = clip_hook.tighten(it, cues, self.silent_then_sound(12.5), PER)
        self.assertGreater(got["in"], 11.5)
        self.assertLessEqual(got["in"], 12.5)

    def test_it_never_moves_into_the_middle_of_a_line(self):
        it = item(10.0, 30.0)
        cues = [(9.0, 13.5, "A long line already running at the start.")]
        got = clip_hook.tighten(it, cues, self.silent_then_sound(12.5), PER)
        self.assertEqual(got["in"], 10.0)

    def test_a_clip_that_starts_with_sound_is_left_alone(self):
        it = item(10.0, 30.0)
        got = clip_hook.tighten(it, [(10.2, 12, "Go.")], peaks(60, 200), PER)
        self.assertEqual(got["in"], 10.0)

    def test_it_does_not_shorten_a_clip_below_the_minimum(self):
        it = item(10.0, 18.5)
        got = clip_hook.tighten(it, [(12.5, 15.0, "x")], self.silent_then_sound(12.5), PER)
        self.assertEqual(got["in"], 10.0)

    def test_the_original_item_is_not_mutated(self):
        it = item(10.0, 30.0)
        clip_hook.tighten(it, [(12.5, 15.0, "x")], self.silent_then_sound(12.5), PER)
        self.assertEqual(it["in"], 10.0)



class BetterStart(unittest.TestCase):
    CUES = [(10.0, 14.0, "And so because of that."), (14.2, 20.0, "Why did nobody say anything?"), (20.2, 40.0, "It was huge. Everybody knew it.")]

    def clip(self):
        return {"in": 9.75, "out": 40.0, "text": " ".join(c[2] for c in self.CUES)}

    def test_a_clip_opening_on_a_continuation_gets_a_later_start(self):
        got = clip_hook.better_start(self.clip(), self.CUES)
        self.assertAlmostEqual(got["in"], 13.95, places=2)
        self.assertTrue(got["text"].startswith("Why did nobody"))
        self.assertEqual(got["out"], 40.0)

    def test_a_strong_opening_has_no_alternative(self):
        cues = [(10.0, 14.0, "Why did nobody say anything?"), (14.2, 40.0, "It was huge.")]
        self.assertIsNone(clip_hook.better_start({"in": 9.75, "out": 40.0, "text": "x"}, cues))

    def test_no_alternative_when_the_rest_is_too_short(self):
        cues = [(10.0, 14.0, "And so it went."), (14.2, 18.0, "Why though?")]
        self.assertIsNone(clip_hook.better_start({"in": 9.75, "out": 18.0, "text": "And so it went."}, cues))

    def test_it_only_starts_after_a_finished_sentence(self):
        cues = [(10.0, 14.0, "And so because"), (14.2, 20.0, "Why did nobody say anything?"), (20.2, 40.0, "It was huge.")]
        got = clip_hook.better_start({"in": 9.75, "out": 40.0, "text": "And so because Why did nobody say anything?"}, cues)
        self.assertTrue(got["text"].startswith("It was huge"))


if __name__ == "__main__":
    unittest.main()
