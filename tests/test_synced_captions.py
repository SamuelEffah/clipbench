import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts import clipper, make_short  # noqa: E402

WORDS = [["I", 0.2, 0.4], ["will", 0.4, 0.7], ["not", 0.7, 1.0], ["lose.", 1.0, 1.5], ["Watch", 2.6, 3.0], ["me", 3.0, 3.3]]


def cues_for(mode, words=WORDS, extra="", span="0:10 - 0:20"):
    text = f"@capmode {mode}\n@words {json.dumps(words)}\n{extra}{span}"
    cuts = make_short.read_cuts(text)
    return make_short.caption_cues([c[:3] for c in cuts], [c[3] for c in cuts])


class PhraseTests(unittest.TestCase):
    def test_phrases_break_at_pauses_and_sentence_ends(self):
        groups = make_short.phrases_of([tuple(w) for w in WORDS])
        self.assertEqual([[w[0] for w in g] for g in groups], [["I", "will", "not"], ["lose."], ["Watch", "me"]])

    def test_phrase_mode_makes_one_cue_per_phrase(self):
        cues = cues_for("phrase")
        self.assertEqual([c[2] for c in cues], ["I will not", "lose.", "Watch me"])
        self.assertAlmostEqual(cues[0][0], 0.2)
        self.assertGreaterEqual(cues[0][1], 1.0)

    def test_word_mode_lights_each_word_in_turn(self):
        cues = cues_for("word")
        lit = [(c[2][0][c[2][1]]) for c in cues]
        self.assertEqual(lit, ["I", "will", "not", "lose.", "Watch", "me"])
        self.assertAlmostEqual(cues[0][1], cues[1][0])

    def test_text_mode_ignores_the_words(self):
        cues = cues_for("text", extra="@caption hello\n")
        self.assertEqual([c[2] for c in cues], ["hello"])

    def test_speed_squeezes_the_timing(self):
        slow = cues_for("phrase")[2][0]
        fast = cues_for("phrase", extra="@speed 2\n")[2][0]
        self.assertAlmostEqual(fast, slow / 2)

    def test_words_past_the_clip_end_are_dropped(self):
        cues = cues_for("phrase", span="0:10 - 0:12")
        self.assertEqual([c[2] for c in cues], ["I will not", "lose."])

    def test_cues_follow_the_clip_offset(self):
        text = f"0:00 - 0:04\n@capmode phrase\n@words {json.dumps(WORDS)}\n0:10 - 0:20"
        cuts = make_short.read_cuts(text)
        cues = make_short.caption_cues([c[:3] for c in cuts], [c[3] for c in cuts])
        self.assertAlmostEqual(cues[0][0], 4.2)

    def test_ass_lights_the_active_word(self):
        out = make_short.ass_text((["a", "b"], 1))
        self.assertIn("{\\1c&H4AD8FF&\\t(0,70,\\fscx106\\fscy106)\\t(70,170,\\fscx100\\fscy100)}b{\\1c&HFFFFFF&\\fscx100\\fscy100}", out)
        self.assertTrue(out.startswith("a "))

    def test_highlight_colour_is_given_as_rgb_and_written_as_bgr(self):
        self.assertIn("\\1c&H00FF00&", make_short.ass_text((["a"], 0), "00ff00"))
        self.assertEqual(make_short.ass_colour("FFD84A"), "&H4AD8FF&")

    def test_bad_words_are_rejected(self):
        for bad in ("nope", '[["x", 2, 1]]', '[["", 0, 1]]', "[1]"):
            with self.assertRaises(SystemExit):
                make_short.parse_option("words", bad)
        with self.assertRaises(SystemExit):
            make_short.parse_option("capmode", "karaoke")


class LookTests(unittest.TestCase):
    def cues(self, text):
        cuts = make_short.read_cuts(text)
        return make_short.caption_cues([c[:3] for c in cuts], [c[3] for c in cuts], (0.5, 0.8))

    def test_a_look_and_highlight_carry_forward_until_changed(self):
        cues = self.cues("@caption a\n@caplook box\n@caphi 00FF00\n0:01 - 0:02\n@caption b\n0:03 - 0:04\n@caption c\n@caplook impact\n0:05 - 0:06")
        self.assertEqual([(c[6], c[7]) for c in cues], [("box", "00FF00"), ("box", "00FF00"), ("impact", "00FF00")])

    def test_clips_without_a_look_use_the_classic_one(self):
        self.assertEqual(self.cues("@caption a\n0:01 - 0:02")[0][6:], ("classic", "FFD84A"))

    def test_each_cue_picks_its_style_and_impact_is_shown_in_capitals(self):
        cues = self.cues("@caption hello\n@caplook impact\n0:01 - 0:02")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "c.ass"
            make_short.write_ass(cues, 1000, str(dest))
            ass = dest.read_text()
        for name in make_short.LOOKS:
            self.assertIn(f"Style: {name},", ass)
        self.assertIn("Style: impact,Impact,", ass)
        self.assertIn("Style: box,Arial,", ass)
        self.assertRegex(ass, r"Dialogue: 0,[^,]+,[^,]+,impact,,0,0,0,,\{[^}]*\}HELLO")

    def test_each_look_styles_its_letters_and_outline_in_its_own_colours(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "c.ass"
            make_short.write_ass([], 1000, str(dest))
            ass = dest.read_text()
        self.assertRegex(ass, r"Style: pop,Arial Black,75,&H00FFFFFF,&H00000000,")
        self.assertRegex(ass, r"Style: stamp,Impact,\d+,&H00FFFFFF,&H002D32E5,&H002D32E5,")

    def test_lit_word_goes_back_to_the_looks_own_letter_colour(self):
        self.assertIn("\\1c&H4AE1FF&", make_short.ass_text((["a", "b"], 0), "00ff00", fill="FFE14A"))

    def test_unknown_look_or_colour_is_rejected(self):
        with self.assertRaises(SystemExit):
            make_short.parse_option("caplook", "comic")
        with self.assertRaises(SystemExit):
            make_short.parse_option("caphi", "yellow")

    def test_export_validates_and_writes_the_look(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "a.mp4"
            video.write_bytes(b"x")
            with mock.patch.object(clipper, "PROJECT_DIR", Path(tmp)):
                clip = {"src": str(video), "in": 1, "out": 9, "caption": "x"}
                text = clipper.export_cuts("sc", {"clips": [{**clip, "capLook": "box", "capHi": "00ff00"}]})[0]
                self.assertIn("@caplook box", text)
                self.assertIn("@caphi 00ff00", text)
                with self.assertRaises(ValueError):
                    clipper.export_cuts("sc", {"clips": [{**clip, "capLook": "comic"}]})
                with self.assertRaises(ValueError):
                    clipper.export_cuts("sc", {"clips": [{**clip, "capHi": "red"}]})


class ExportTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.video = Path(tmp.name) / "a.mp4"
        self.video.write_bytes(b"x")
        patch = mock.patch.object(clipper, "PROJECT_DIR", Path(tmp.name))
        patch.start()
        self.addCleanup(patch.stop)

    def export(self, **extra):
        clip = {"src": str(self.video), "in": 1, "out": 9, **extra}
        return clipper.export_cuts("sc", {"clips": [clip]})[0]

    def test_synced_words_round_trip_through_the_cut_list(self):
        text = self.export(capMode="word", words=WORDS, caption="x")
        cuts = make_short.read_cuts(text)
        self.assertEqual(cuts[0][3]["capmode"], "word")
        self.assertEqual(cuts[0][3]["words"][1], ("will", 0.4, 0.7))

    def test_static_style_leaves_the_words_out(self):
        text = self.export(capMode="text", words=WORDS)
        self.assertNotIn("@words", text)

    def test_words_trimmed_off_the_front_are_not_rendered(self):
        words = [["gone", -0.8, -0.3], ["half", -0.2, 0.3], ["kept", 0.5, 0.9]]
        cuts = make_short.read_cuts(self.export(capMode="word", words=words))
        self.assertEqual(cuts[0][3]["words"], [("half", 0.0, 0.3), ("kept", 0.5, 0.9)])

    def test_words_follow_a_trim_made_after_timing(self):
        # Timed with the in point at 0.5, then the start trimmed to 1: the speech is now half a second earlier.
        words = [["gone", 0.1, 0.4], ["kept", 1.0, 1.4]]
        cuts = make_short.read_cuts(self.export(capMode="word", words=words, wordsIn=0.5))
        self.assertEqual(cuts[0][3]["words"], [("kept", 0.5, 0.9)])

    def test_all_words_trimmed_away_leaves_a_static_clip(self):
        text = self.export(capMode="word", words=[["gone", -0.8, -0.3]], caption="x")
        self.assertNotIn("@words", text)
        self.assertNotIn("@capmode", text)

    def test_bad_style_or_words_are_refused(self):
        with self.assertRaises(ValueError):
            self.export(capMode="karaoke", words=WORDS)
        with self.assertRaises(ValueError):
            self.export(capMode="word", words=[["x"]])

    def test_spoken_words_come_from_whisper_segments(self):
        heard = {"segments": [{"words": [{"word": " Hi", "start": 0.0, "end": 0.4}, {"word": " ", "start": 0.4, "end": 0.5}]}]}
        self.assertEqual(clipper.spoken_words(heard), [["Hi", 0.0, 0.4]])


if __name__ == "__main__":
    unittest.main()
