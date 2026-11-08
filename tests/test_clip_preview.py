import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import clipper


def clip(**extra):
    return {"src": "/x/a.mp4", "in": 1.0, "out": 3.0, **extra}


class PreviewClipTests(unittest.TestCase):
    def test_clip_stands_alone_in_the_top_lane(self):
        project = {"template": "split", "audio": [{"x": 1}], "clips": [clip(), clip(lane="bottom", transition="fade"), clip()]}
        sub = clipper.preview_clip(project, 1)
        self.assertEqual(len(sub["clips"]), 1)
        self.assertEqual(sub["clips"][0]["lane"], "top")
        self.assertEqual(sub["clips"][0]["transition"], "none")
        self.assertEqual(sub["template"], "full")
        self.assertEqual(sub["audio"], [])

    def test_caption_style_is_inherited_from_earlier_clips(self):
        project = {"clips": [clip(capX=0.3, capY=0.4, capScale=1.5, capLook="box"), clip(capHi="FF6FAE"), clip(capLook="impact")]}
        got = clipper.preview_clip(project, 1)["clips"][0]
        self.assertEqual((got["capX"], got["capY"], got["capScale"], got["capLook"], got["capHi"]), (0.3, 0.4, 1.5, "box", "FF6FAE"))
        self.assertNotEqual(clipper.preview_clip(project, 2)["clips"][0]["capLook"], "box")
        self.assertNotIn("capLook", clipper.preview_clip({"clips": [clip(), clip(capLook="box")]}, 0)["clips"][0])

    def test_bottom_lane_captions_do_not_carry_into_the_top_lane(self):
        project = {"template": "split", "clips": [clip(capLook="impact"), clip(lane="bottom", capLook="box", capX=0.1, capY=0.2), clip()]}
        got = clipper.preview_clip(project, 2)["clips"][0]
        self.assertEqual(got["capLook"], "impact")
        self.assertNotIn("capX", got)

    def test_a_bottom_clip_keeps_its_own_caption_style(self):
        project = {"template": "split", "clips": [clip(), clip(lane="bottom", capLook="box")]}
        self.assertEqual(clipper.preview_clip(project, 1)["clips"][0]["capLook"], "box")

    def test_bad_index_is_refused(self):
        for index in (None, -1, 5, "0"):
            with self.assertRaises(ValueError):
                clipper.preview_clip({"clips": [clip()]}, index)


if __name__ == "__main__":
    unittest.main()


class FitTranslationTests(unittest.TestCase):
    def test_english_follows_the_original_timing_and_its_pause(self):
        heard = [["a", 1.0, 1.4], ["b", 1.4, 1.8], ["c", 3.0, 3.4], ["d", 3.4, 3.8]]
        got = clipper.fit_translation(heard, [{"start": 0.9, "end": 3.9, "text": "one two three four"}])
        self.assertEqual([w[0] for w in got], ["one", "two", "three", "four"])
        self.assertAlmostEqual(got[0][1], 1.0, places=1)
        self.assertLess(got[1][2], 2.0)
        self.assertGreater(got[2][1], 2.9)
        self.assertAlmostEqual(got[3][2], 3.8, places=1)

    def test_each_segment_uses_the_words_heard_during_it(self):
        heard = [["a", 0.0, 0.5], ["b", 0.5, 1.0], ["c", 5.0, 5.5], ["d", 5.5, 6.0]]
        segs = [{"start": 0.0, "end": 1.0, "text": "hello"}, {"start": 5.0, "end": 6.0, "text": "good bye"}]
        got = clipper.fit_translation(heard, segs)
        self.assertEqual(got[0][1:], [0.0, 1.0])
        self.assertTrue(all(w[1] >= 5.0 for w in got[1:]))

    def test_nothing_heard_or_no_segments_gives_nothing(self):
        self.assertEqual(clipper.fit_translation([], [{"start": 0, "end": 1, "text": "hi"}]), [])
        self.assertEqual(clipper.fit_translation([["a", 0, 1]], [{"start": 0, "end": 1, "text": "  "}]), [])

    def test_a_pause_lands_after_the_punctuation_when_one_is_near(self):
        heard = [["こんにちは、", 0.0, 0.6], ["今日", 1.2, 1.8], ["は", 1.8, 2.4]]
        got = clipper.fit_translation(heard, [{"start": 0.0, "end": 2.4, "text": "Hello, it is a good day"}])
        self.assertEqual(got[0][:1], ["Hello,"])
        self.assertAlmostEqual(got[0][2], 0.6, places=1)
        self.assertAlmostEqual(got[1][1], 1.2, places=1)
