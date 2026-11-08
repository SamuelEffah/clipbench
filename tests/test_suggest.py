import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import suggest  # noqa: E402

CUES = [
    (10.0, 13.0, "What are you doing?!"),
    (13.2, 16.0, "Stop. Right now!"),
    (16.2, 19.0, "I can't believe this."),
    (60.0, 62.0, "Anyway, about the weather."),
    (62.5, 66.0, "It has been quite mild lately."),
    (66.5, 72.0, "I suppose that is nice."),
]


class Candidates(unittest.TestCase):
    def test_windows_are_long_enough_and_end_on_a_sentence(self):
        found = suggest.candidates(CUES, 100, [])
        self.assertTrue(found)
        for c in found:
            self.assertGreaterEqual(c["out"] - c["in"], suggest.MIN_LEN)
            self.assertLessEqual(c["out"] - c["in"], suggest.MAX_LEN + 2)
        self.assertTrue(found[0]["text"].startswith("What are you doing?!"))
        self.assertTrue(found[0]["text"].endswith("believe this."))

    def test_lines_far_apart_are_not_joined(self):
        for c in suggest.candidates(CUES, 100, []):
            self.assertFalse("What" in c["text"] and "weather" in c["text"])

    def test_edges_snap_to_nearby_scene_cuts(self):
        found = suggest.candidates(CUES, 100, [9.6, 19.8])
        self.assertEqual(found[0]["in"], 9.6)
        self.assertEqual(found[0]["out"], 19.8)

    def test_far_scene_cuts_are_ignored(self):
        found = suggest.candidates(CUES, 100, [3.0, 40.0])
        self.assertEqual(found[0]["in"], 9.75)

    def test_end_never_passes_the_video(self):
        found = suggest.candidates([(0.0, 4.0, "Hi."), (4.2, 9.0, "Go!")], 9.1, [])
        self.assertLessEqual(found[0]["out"], 9.1)


class Scoring(unittest.TestCase):
    def test_a_shout_scores_higher_than_a_steady_hum(self):
        loud = [20] * 100 + [255] * 20 + [20] * 100
        hum = [100] * 220
        item = {"in": 0, "out": 11, "text": "Hello."}
        a = suggest.heuristic(dict(item), loud, 20)
        b = suggest.heuristic(dict(item), hum, 20)
        self.assertGreater(a, b)

    def test_no_audio_still_scores(self):
        self.assertGreaterEqual(suggest.heuristic({"in": 0, "out": 10, "text": "Run!"}, [], 20), 0)

    def test_punchy_wording_beats_flat(self):
        self.assertGreater(suggest.wording("What?! No! Stop!"), suggest.wording("It was a long and uneventful afternoon in the village."))

    def test_chosen_clips_do_not_overlap_and_best_comes_first(self):
        items = [{"in": 0, "out": 10, "score": 0.5}, {"in": 5, "out": 15, "score": 0.9}, {"in": 20, "out": 30, "score": 0.4}]
        got = suggest.spread_out(items, 10)
        self.assertEqual([c["score"] for c in got], [0.9, 0.4])


class Model(unittest.TestCase):
    def test_suggest_without_a_model_ranks_the_shout_first(self):
        peaks = [10] * 20 * 100
        peaks[11 * 20:12 * 20] = [255] * 20
        got = suggest.suggest(CUES, 100, [], peaks, 20)
        self.assertLess(got[0]["in"], 20)

    def test_a_model_changes_the_order_and_supplies_the_reason(self):
        with mock.patch.object(suggest, "ask", return_value={}) as ask:
            ask.side_effect = lambda model, batch: {n: (1.0 if "weather" in it["text"] else 0.0, "funny") for n, it in enumerate(batch, 1)}
            got = suggest.suggest(CUES, 100, [], ([200] * 20 + [10] * 20) * 50, 20, model="qwen3")
        self.assertIn("weather", got[0]["text"])
        self.assertEqual(got[0]["why"], "funny")

    def test_a_failed_model_batch_falls_back_to_the_ranking_alone(self):
        import urllib.error
        with mock.patch.object(suggest, "ask", side_effect=urllib.error.URLError("down")):
            got = suggest.suggest(CUES, 100, [], ([200] * 20 + [10] * 20) * 50, 20, model="qwen3")
        self.assertTrue(got)

    def test_the_model_reads_at_most_forty_candidates(self):
        cues = [(t * 4.0, t * 4.0 + 3.5, f"Line {t} ends here.") for t in range(300)]
        batches = []
        with mock.patch.object(suggest, "ask", side_effect=lambda model, batch: batches.append(batch) or {}):
            suggest.suggest(cues, 1200, [], [], 20, model="qwen3")
        self.assertEqual(suggest.LLM_SHORTLIST, 40)
        self.assertLessEqual(sum(len(b) for b in batches), 40)
        self.assertEqual(len(batches), 40)

    def test_the_shortlist_is_scored_best_measured_first_so_the_top_settles_early(self):
        # Every section still gets its places; the order within the forty is by measured score, so the moments most
        # likely to end up on top are the first the model answers for, and the list stops shifting early.
        items = [{"in": t * 4.0, "out": t * 4.0 + 30, "text": f"line {t}", "score": (t * 7919 % 300) / 300} for t in range(300)]
        picked = suggest.model_shortlist(items, 1200)
        self.assertEqual(len(picked), 40)
        self.assertEqual([p["score"] for p in picked], sorted((p["score"] for p in picked), reverse=True))
        sections = {int(p["in"] / 1200 * 12) for p in picked}
        self.assertEqual(len(sections), 12)

    def test_the_shortlist_does_not_spend_its_places_on_the_same_stretch_twice(self):
        # Measured 2026-11-07 on the Conan file: 29 of the 40 places went to windows sharing most of their span with an
        # earlier one, so the model read about eleven moments three or four times over.
        items = []
        for t in range(60):
            start = t * 20.0
            for k, (shift, length) in enumerate(((0, 30), (0.2, 30), (0, 39), (2, 36))):
                items.append({"in": start + shift, "out": start + shift + length, "text": f"line {t} {k}", "score": 0.9 - t * 0.01 - k * 0.001})
        picked = suggest.model_shortlist(items, 1200)
        self.assertEqual(len(picked), 40)
        for a in picked:
            for b in picked:
                if a is not b:
                    shared = max(0.0, min(a["out"], b["out"]) - max(a["in"], b["in"]))
                    self.assertLess(shared / min(a["out"] - a["in"], b["out"] - b["in"]), suggest.SHORTLIST_OVERLAP)
        self.assertEqual(len({int(p["in"] / 1200 * 12) for p in picked}), 12, "every section still gets its places")

    def test_each_excerpt_is_scored_alone(self):
        # Measured 2026-11-07 with qwen2.5:3b on ten Conan O'Brien excerpts: in one list the scores ran 0.2, 0.4, ... 1.0 by position and
        # reversed they were a flat 0.3; asked one at a time they held between two passes and told the excerpts apart.
        batches = []
        with mock.patch.object(suggest, "ask", side_effect=lambda model, batch: batches.append(batch) or {}):
            suggest.suggest(CUES, 100, [], [], 20, model="qwen3")
        self.assertTrue(batches)
        self.assertEqual({len(b) for b in batches}, {1})

    def test_the_best_so_far_is_handed_over_after_each_answer(self):
        # Scoring one excerpt at a time takes about a minute for a shortlist, so the list fills in as the answers come.
        seen = []
        with mock.patch.object(suggest, "ask", side_effect=lambda model, batch: {1: (0.9, "cliffhanger")}):
            got = suggest.suggest(CUES, 100, [], [], 20, model="qwen3", partial=lambda clips: seen.append(clips))
        self.assertGreater(len(seen), 1)
        self.assertEqual(seen[-1], got)
        self.assertEqual(len(seen[0]), 1, "the first handover carries the one moment answered for")
        self.assertGreater(len(seen[-1]), 1)
        for clips in seen:
            # Only answered moments: one not reached yet would float above them on its measured score alone.
            self.assertTrue(all(s["why"] == "cliffhanger" for s in clips))
            self.assertEqual(clips, sorted(clips, key=lambda s: -s["score"]))
            self.assertTrue(all("silent" not in s for s in clips))

    def test_model_pick_prefers_a_known_family_and_skips_embedders(self):
        self.assertEqual(suggest.pick_model(["nomic-embed-text", "qwen3:8b"]), "qwen3:8b")
        self.assertEqual(suggest.pick_model([]), None)

    def test_a_label_the_model_was_not_offered_is_dropped(self):
        self.assertEqual(suggest.clean_reason("five words at most"), "")
        self.assertEqual(suggest.clean_reason("Reveal"), "reveal")
        self.assertEqual(suggest.clean_reason(None), "")

    def test_a_word_from_a_label_s_definition_counts_as_that_label(self):
        # Small models answer with the words the definition used, "banter" for a joke, "secret" for a reveal.
        self.assertEqual(suggest.clean_reason("banter"), "joke")
        self.assertEqual(suggest.clean_reason("Punchline"), "joke")
        self.assertEqual(suggest.clean_reason("secret"), "reveal")
        self.assertEqual(suggest.clean_reason("outrageous"), "shock")
        self.assertEqual(suggest.clean_reason("teaches"), "explanation")
        self.assertEqual(suggest.clean_reason("<label>"), "")

    def test_the_prompt_defines_every_label_and_its_example_favours_none(self):
        # A small model copies the example answer, so the example must not name a real label and each label needs a line saying what counts.
        import json
        import re
        example = re.search(r"Answer with only JSON: (\{.*\})", suggest.PROMPT).group(1)
        for row in json.loads(example)["scores"]:
            self.assertEqual(suggest.clean_reason(row["why"]), "")
        for label in suggest.WHY:
            self.assertRegex(suggest.PROMPT, rf"\n{label}: \S", f"{label} has no definition line")
        self.assertIn("joke: ", suggest.PROMPT)
        self.assertLess(suggest.PROMPT.index("joke:"), suggest.PROMPT.index("explanation:"))

    def test_ollama_down_means_no_models(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError):
            self.assertEqual(suggest.ollama_models(), [])


if __name__ == "__main__":
    unittest.main()


class ProfileAndHook(unittest.TestCase):
    def test_clips_carry_a_breakdown_of_what_scored_them(self):
        got = suggest.suggest(CUES, 100, [], [10] * 2000, 20)
        self.assertEqual(set(got[0]["parts"]), {"energy", "words", "hook"})
        self.assertTrue(all(0 <= v <= 100 for v in got[0]["parts"].values()))

    def test_a_clip_that_opens_on_a_continuation_ranks_below_one_that_opens_strong(self):
        cues = [(10.0, 19.0, "Why did nobody tell me? It is huge."), (60.0, 69.0, "And so because of that it is huge.")]
        got = suggest.suggest(cues, 100, [], ([200] * 20 + [10] * 20) * 50, 20)
        self.assertLess(got[0]["in"], 20)

    def test_dead_air_at_the_start_is_trimmed(self):
        peaks = [2] * 2000
        for i in range(12 * 20 + 10, 40 * 20):
            peaks[i] = 200
        cues = [(12.5, 22.0, "Finally something happens here."), (22.5, 30.0, "And it keeps going.")]
        got = suggest.suggest(cues, 100, [], peaks, 20)
        self.assertGreaterEqual(got[0]["in"], 12.0)

    def test_the_given_profile_is_used_instead_of_measuring_again(self):
        with mock.patch.object(suggest.clip_profile, "profile") as measure:
            suggest.suggest(CUES, 100, [], [10] * 2000, 20, profile={"kind": "speech"})
        measure.assert_not_called()


class ShortLength(unittest.TestCase):
    def test_a_length_that_fits_a_short_is_not_marked_down(self):
        self.assertEqual(suggest.length_fit(35), 1)
        self.assertLess(suggest.length_fit(12), suggest.length_fit(28))
        self.assertLess(suggest.length_fit(60), suggest.length_fit(45))

    def test_a_talk_is_offered_at_short_length_and_that_beats_a_clip_cut_short(self):
        cues = [(10.0 + 4 * n, 13.5 + 4 * n, f"Line number {n}, and it matters.") for n in range(15)]
        got = suggest.suggest(cues, 100, [], ([200] * 20 + [10] * 20) * 50, 20)
        length = got[0]["out"] - got[0]["in"]
        self.assertTrue(suggest.SHORT_MIN <= length <= suggest.SHORT_MAX + 2, length)

    def test_a_moment_with_pauses_in_it_still_runs_on_to_short_length(self):
        cues = [(10.0 + 6 * n, 13.5 + 6 * n, f"Pause number {n} is here.") for n in range(10)]
        got = suggest.suggest(cues, 100, [], ([200] * 20 + [10] * 20) * 50, 20)
        self.assertTrue(suggest.SHORT_MIN <= got[0]["out"] - got[0]["in"] <= suggest.SHORT_MAX + 2)


class WeakOpenings(unittest.TestCase):
    def test_a_clip_opening_on_a_continuation_is_offered_from_its_next_sentence(self):
        cues = [(10.0, 14.0, "And so because of that."), (14.2, 22.0, "Why did nobody say anything?"), (22.2, 30.0, "It was huge. Everybody knew.")]
        got = suggest.suggest(cues, 100, [], ([200] * 20 + [10] * 20) * 50, 20)
        self.assertTrue(got[0]["text"].startswith("Why did nobody"))


class Describe(unittest.TestCase):
    def test_a_hand_cut_stretch_is_described_like_a_suggestion(self):
        peaks = [10] * 2000
        peaks[11 * 20:12 * 20] = [255] * 20
        got = suggest.describe(9.5, 20.0, CUES, 100, [9.6], peaks, 20, profile={"kind": "speech"})
        self.assertEqual((got["in"], got["out"]), (9.5, 20.0))
        self.assertEqual(got["text"], "What are you doing?! Stop. Right now! I can't believe this.")
        self.assertEqual(set(got["parts"]), {"energy", "words", "hook"})
        self.assertEqual(got["profile"], "speech")
        self.assertTrue(0 < got["score"] <= 1)
        self.assertNotIn("silent", got)

    def test_a_stretch_with_nothing_said_is_judged_on_its_sound(self):
        got = suggest.describe(30, 60, CUES, 100, [], [200] * 2000, 20, profile={"kind": "visual"}, motion={"per_sec": 4, "values": [9] * 400})
        self.assertEqual(got["text"], "")
        self.assertIn("motion", got["parts"])
        self.assertIn(got["why"], ("Loud moment", "Busy moment", "Steady sound"))
        self.assertEqual(got["profile"], "visual")

    def test_scoring_a_candidate_is_the_same_whether_done_alone_or_in_the_list(self):
        peaks = ([200] * 20 + [10] * 20) * 50
        listed = suggest.suggest(CUES, 100, [], peaks, 20)[0]
        alone = suggest.describe(listed["in"], listed["out"], CUES, 100, [], peaks, 20)
        self.assertEqual(alone["parts"], listed["parts"])
        self.assertEqual(alone["score"], listed["score"])
