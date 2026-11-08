import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import learning  # noqa: E402

# Figures copied from a real channel on 2026-11-07.
STATS = {
    "vidAAAAAAAA1": {"views": 1337, "avg_percent": 87.19, "gone": 0},
    "W2Rjw3XWB2M": {"views": 1311, "avg_percent": 95.84, "gone": 0},
    "J5_4uPvEM_M": {"views": 1238, "avg_percent": 40.99, "gone": 0},
    "R0xX2_weXq8": {"views": 389, "avg_percent": 57.22, "gone": 0},
    "UapQj2ZCIvA": {"views": 0, "avg_percent": None, "gone": 1},
}
JOKE = {"text": "a line", "why": "joke", "parts": {"hook": 80, "energy": 70, "words": 65}, "score": 0.8, "profile": "speech"}
QUIET = {"text": "b line", "why": "explanation", "parts": {"hook": 20, "energy": 15, "words": 30}, "score": 0.5, "profile": "speech"}


class Features(unittest.TestCase):
    def test_a_moment_is_described_by_its_label_and_high_or_low_parts(self):
        self.assertEqual(learning.features(JOKE), {"why:joke", "why:joke@speech", "hook:high", "energy:high", "words:high", "profile:speech"})
        self.assertEqual(learning.features(QUIET), {"why:explanation", "why:explanation@speech", "hook:low", "energy:low", "words:low", "profile:speech"})

    def test_a_label_is_also_learned_together_with_the_kind_of_video(self):
        self.assertIn("why:joke@speech", learning.features(JOKE))
        self.assertNotIn("why:joke@speech", learning.features({**JOKE, "profile": None}))
        self.assertEqual({f for f in learning.features({"why": "joke"}) if "@" in f}, set())

    def test_motion_counts_only_when_measured_and_junk_is_ignored(self):
        self.assertIn("motion:high", learning.features({"parts": {"motion": 90}}))
        self.assertEqual(learning.features({"parts": {"hook": "x"}, "why": 3}), set())
        self.assertEqual(learning.features(None), set())


class Outcomes(unittest.TestCase):
    def test_typical_views_is_the_median_of_videos_still_up(self):
        self.assertEqual(learning.typical_views(STATS), (1238 + 1311) / 2)
        self.assertIsNone(learning.typical_views({"x": {"views": 0, "gone": 1}}))

    def test_a_short_that_held_viewers_and_drew_views_scores_high_and_a_flop_low(self):
        typical = learning.typical_views(STATS)
        held = learning.outcome(STATS["W2Rjw3XWB2M"], typical)
        dropped = learning.outcome(STATS["J5_4uPvEM_M"], typical)
        few = learning.outcome(STATS["R0xX2_weXq8"], typical)
        self.assertGreater(held, dropped)
        self.assertGreater(dropped, few)
        self.assertLessEqual(held, learning.OUTCOME_MAX)
        self.assertGreaterEqual(few, -1.0)

    def test_a_video_without_watch_figures_is_judged_on_views_alone(self):
        self.assertGreater(learning.outcome({"views": 3000, "avg_percent": None}, 1000), 0)
        self.assertIsNone(learning.outcome(STATS["UapQj2ZCIvA"], 1000))


class Lessons(unittest.TestCase):
    def test_each_feature_remembers_its_mean_value_and_how_often_it_was_seen(self):
        got = learning.lessons([(JOKE, 1.0), (JOKE, 0.5), (QUIET, -1.0)])
        self.assertEqual(got["why:joke"], (0.75, 2))
        self.assertEqual(got["hook:low"], (-1.0, 1))
        self.assertEqual(got["profile:speech"], ((1.0 + 0.5 - 1.0) / 3, 3))

    def test_kept_and_skipped_decisions_become_examples(self):
        reviews = [{"decision": "keep", "moment": JOKE}, {"decision": "skip", "moment": QUIET}, {"decision": "skip", "moment": {}}]
        got = learning.review_examples(reviews)
        self.assertEqual(got, [(JOKE, learning.KEEP_VALUE), (QUIET, learning.SKIP_VALUE)])


class Adjusting(unittest.TestCase):
    def test_a_moment_like_the_ones_that_did_well_moves_up_and_nothing_else_is_touched(self):
        lessons = learning.lessons([(JOKE, 1.5)] * 10 + [(QUIET, -1.0)] * 10)
        items = [{**QUIET, "in": 0, "out": 30, "score": 0.6}, {**JOKE, "in": 40, "out": 70, "score": 0.5}]
        got = learning.adjust(items, lessons)
        self.assertEqual([it["in"] for it in got], [40, 0])
        self.assertGreater(got[0]["score"], 0.5)
        self.assertLess(got[1]["score"], 0.6)
        self.assertEqual(items[0]["score"], 0.6)
        self.assertEqual(items[1]["score"], 0.5)

    def test_thin_evidence_barely_moves_a_score(self):
        one = learning.adjust([{**JOKE, "score": 0.5}], learning.lessons([(JOKE, 1.5)]))[0]["score"]
        many = learning.adjust([{**JOKE, "score": 0.5}], learning.lessons([(JOKE, 1.5)] * 20))[0]["score"]
        self.assertLess(one - 0.5, (many - 0.5) / 2)
        self.assertLessEqual(many, 0.5 * (1 + learning.LEARN_WEIGHT * learning.OUTCOME_MAX) + 1e-9)

    def test_each_moment_says_in_a_line_why_it_moved(self):
        lessons = learning.lessons([(JOKE, 1.5)] * 10 + [(QUIET, -1.0)] * 10)
        up, down = learning.adjust([{**JOKE, "score": 0.5}, {**QUIET, "score": 0.5}], lessons)
        self.assertEqual(up["learned"], {"delta": up["learned"]["delta"], "note": "jokes did well before"})
        self.assertGreater(up["learned"]["delta"], 0)
        self.assertEqual(down["learned"]["note"], "explanations did poorly before")

    def test_a_list_that_all_moved_the_same_way_carries_no_note(self):
        # Every joke in a talk video moving by the same amount says nothing about which to pick, so none wears a note.
        lessons = learning.lessons([(JOKE, 1.5)] * 10)
        items = [{**JOKE, "in": 0, "score": 0.6}, {**JOKE, "in": 40, "score": 0.5}, {**JOKE, "in": 80, "score": 0.4}]
        got = learning.adjust(items, lessons)
        self.assertEqual([it["in"] for it in got], [0, 40, 80])
        self.assertTrue(all("learned" not in it for it in got))
        self.assertGreater(got[0]["score"], 0.6)
        one = learning.adjust([{**JOKE, "score": 0.5}], lessons)[0]
        self.assertEqual(one["learned"]["note"], "jokes did well before")

    def test_the_strongest_part_names_the_note_when_the_label_is_not_what_mattered(self):
        loud = {"why": "action", "parts": {"energy": 90}}
        lessons = learning.lessons([(loud, 1.5)] * 10 + [({"why": "action", "parts": {"energy": 10}}, -1.0)] * 10)
        got = learning.adjust([{**loud, "score": 0.5}], lessons)[0]
        self.assertEqual(got["learned"]["note"], "loud moments did well before")

    def test_the_note_agrees_with_the_way_the_score_moved(self):
        # One kept and one skipped moment that share most features: the one lesson pointing up must not name a score that fell.
        kept = {"why": "explanation", "parts": {"hook": 20, "energy": 70}, "profile": "speech"}
        skipped = {"why": "explanation", "parts": {"hook": 80, "energy": 70}, "profile": "speech"}
        lessons = learning.lessons([(kept, learning.KEEP_VALUE), (skipped, learning.SKIP_VALUE)])
        got = learning.adjust([{**kept, "score": 0.5}], lessons)[0]["learned"]
        self.assertLess(got["delta"], 0)
        self.assertEqual(got["note"], "explanations did poorly before")

    def test_a_label_that_works_in_one_kind_of_video_and_not_another_is_learned_apart(self):
        talk, cuts = {**JOKE, "profile": "speech"}, {**JOKE, "profile": "visual"}
        lessons = learning.lessons([(talk, 1.5)] * 10 + [(cuts, -1.0)] * 10)
        up = learning.adjust([{**talk, "score": 0.5}], lessons)[0]
        down = learning.adjust([{**cuts, "score": 0.5}], lessons)[0]
        self.assertGreater(up["score"], 0.5)
        self.assertLess(down["score"], 0.5)
        self.assertEqual(up["learned"]["note"], "jokes in talk videos did well before")
        self.assertEqual(down["learned"]["note"], "jokes in fast-cut videos did poorly before")
        plain = learning.adjust([{**JOKE, "profile": None, "score": 0.5}], lessons)[0]
        self.assertEqual(plain["learned"]["note"], "jokes did well before")

    def test_without_lessons_or_features_nothing_changes(self):
        items = [{"in": 0, "out": 10, "score": 0.4}]
        self.assertEqual(learning.adjust(items, {}), items)
        self.assertEqual(learning.adjust(items, learning.lessons([(JOKE, 1.0)])), items)
        self.assertNotIn("learned", learning.adjust([{**JOKE, "score": 0.5}], {})[0])


class PublishedShorts(unittest.TestCase):
    def test_a_short_is_matched_to_its_upload_or_to_a_channel_video_with_its_title(self):
        shorts = [{"name": "monster", "title": "Would you open the box? #anime", "upload": {"state": "done", "video_id": "vidAAAAAAAA1"}},
                  {"name": "rider", "title": "he never backs down | Some Show #shorts", "upload": {"state": "none"}},
                  {"name": "fit_test", "title": "", "upload": {"state": "none"}}]
        channel = [{"video_id": "vidAAAAAAAA2", "title": "he never backs down | Some Show #shorts"}, {"video_id": "x", "title": ""}]
        self.assertEqual(learning.published(shorts, channel), {"monster": "vidAAAAAAAA1", "rider": "vidAAAAAAAA2"})

    def test_titles_match_without_hashtags_or_a_tail_added_on_youtube(self):
        # Titles as they stand on the channel against the title files of the Shorts they were rendered from.
        channel = [{"video_id": "vidAAAAAAAA3", "title": "the longest night is your own #shorts #anime #animemoments"},
                   {"video_id": "vidAAAAAAAA2", "title": "he never backs down #shorts #anime #animemoments"},
                   {"video_id": "vidAAAAAAAA4", "title": "Which twin is real? #shorts #viral #anime"}]
        shorts = [{"name": "prison_clean", "title": "the longest night is your own #shorts", "upload": {}},
                  {"name": "rider", "title": "he never backs down | Some Show #shorts", "upload": {}},
                  {"name": "short_title", "title": "Which #shorts", "upload": {}},
                  {"name": "other", "title": "a title nothing was called", "upload": {}}]
        self.assertEqual(learning.published(shorts, channel), {"prison_clean": "vidAAAAAAAA3", "rider": "vidAAAAAAAA2"})


class MomentOfClip(unittest.TestCase):
    def test_the_suggestion_covering_most_of_the_clip_is_its_moment(self):
        suggestions = [{"in": 10, "out": 40, **JOKE}, {"in": 100, "out": 130, **QUIET}]
        self.assertEqual(learning.moment_of({"in": 12, "out": 38}, suggestions), {"in": 10, "out": 40, **JOKE})
        self.assertEqual(learning.moment_of({"in": 95, "out": 125}, suggestions), {"in": 100, "out": 130, **QUIET})
        self.assertIsNone(learning.moment_of({"in": 50, "out": 80}, suggestions))
        self.assertIsNone(learning.moment_of({"in": 30, "out": 60}, suggestions))


if __name__ == "__main__":
    unittest.main()


class HandCutShorts(unittest.TestCase):
    def test_a_clip_no_suggestion_covers_teaches_through_the_moment_measured_when_it_was_rendered(self):
        measured = {"src": "/v/ep.mkv", "in": 873.4, "out": 905.0, "text": "said", "why": "Loud moment", "parts": {"hook": 90, "energy": 80, "words": 10}, "profile": "visual"}
        snapshot = {"clips": [{"src": "/v/ep.mkv", "in": 873.4, "out": 905.0, "lane": "top"}, {"src": "/v/ep.mkv", "in": 1, "out": 5, "lane": "top"}], "moments": [measured]}
        stats = {"v1": {"views": 1300, "avg_percent": 90.0, "gone": 0}, "v2": {"views": 400, "avg_percent": 50.0, "gone": 0}}
        got = learning.published_examples({"short": "v1"}, stats, lambda name: snapshot, lambda src: [])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][0], measured)
        self.assertGreater(got[0][1], 0)

    def test_a_saved_suggestion_is_preferred_over_the_measurement(self):
        measured = {"src": "/v/ep.mkv", "in": 10, "out": 40, "why": "Loud moment", "parts": {}}
        suggested = {"in": 10, "out": 40, "why": "joke", "parts": {"hook": 80}}
        snapshot = {"clips": [{"src": "/v/ep.mkv", "in": 10, "out": 40}], "moments": [measured]}
        got = learning.published_examples({"s": "v"}, {"v": {"views": 10, "avg_percent": 70, "gone": 0}}, lambda n: snapshot, lambda src: [suggested])
        self.assertEqual(got[0][0], suggested)


def curve(drop_from, drop_to, floor=0.4):
    """A retention curve of 100 points that stays at 1 until `drop_from` of the Short, then falls evenly to `floor` by `drop_to`."""
    def at(f):
        if f <= drop_from:
            return 1.0
        if f >= drop_to:
            return floor
        return 1.0 - (1.0 - floor) * (f - drop_from) / (drop_to - drop_from)
    return [at(i / 100) for i in range(100)]


class RetentionAlongTheShort(unittest.TestCase):
    def test_clip_lengths_follow_speed_and_a_held_frame(self):
        self.assertEqual(learning.clip_lengths([{"in": 10, "out": 20}, {"in": 0, "out": 10, "speed": 2, "freeze": 1}]), [10.0, 6.0])

    def test_a_stretch_that_loses_viewers_faster_than_the_short_as_a_whole_is_marked_down(self):
        c = curve(0.5, 1.0)
        self.assertAlmostEqual(learning.hold_value(curve(0, 1, 1.0), 0, 15, 30), 0.0)
        self.assertGreater(learning.hold_value(c, 0, 15, 30), 0)
        self.assertLess(learning.hold_value(c, 15, 30, 30), 0)
        self.assertEqual(learning.hold_value(c, 0, 15, 30), 1.0)
        self.assertGreaterEqual(learning.hold_value(c, 15, 30, 30), -1.0)

    def test_without_a_usable_curve_a_stretch_is_judged_by_nothing(self):
        self.assertIsNone(learning.hold_value([], 0, 10, 30))
        self.assertIsNone(learning.hold_value([0.0] * 100, 0, 10, 30))
        self.assertIsNone(learning.hold_value(curve(0.5, 1.0), 0, 10, 0))

    def test_a_clip_teaches_its_whole_moment_by_its_hold_and_its_hook_by_its_opening(self):
        c = curve(0.0, 0.1, 0.9)  # everyone who leaves, leaves in the first three seconds
        got = learning.stretch_examples(JOKE, 0.4, c, 0, 15, 30)
        self.assertEqual([m for m, _ in got], [JOKE, {"parts": {"hook": 80}}])
        whole, opening = (v for _, v in got)
        self.assertGreater(whole, opening)
        self.assertLess(opening, 0.4)
        self.assertGreaterEqual(opening, -1.0)

    def test_a_clip_after_the_leavers_have_gone_holds_better_than_par_and_moves_up(self):
        c = curve(0.0, 0.1, 0.9)
        got = learning.stretch_examples(QUIET, 0.4, c, 15, 30, 30)
        self.assertEqual([m for m, _ in got], [QUIET, {"parts": {"hook": 20}}])
        self.assertTrue(all(v > 0.4 for _, v in got))

    def test_without_a_curve_or_a_hook_the_moment_is_the_only_example_at_the_short_s_value(self):
        self.assertEqual(learning.stretch_examples(JOKE, 0.4, None, 0, 15, 30), [(JOKE, 0.4)])
        self.assertEqual(learning.stretch_examples({"why": "joke"}, 0.4, curve(0.5, 1.0), 0, 15, 30)[1:], [])

    def test_published_shorts_teach_each_clip_by_where_its_viewers_went(self):
        first = {"in": 10, "out": 25, "why": "joke", "parts": {"hook": 80}}
        second = {"in": 100, "out": 115, "why": "explanation", "parts": {"hook": 20}}
        snapshot = {"clips": [{"src": "/v/a.mp4", "in": 10, "out": 25}, {"src": "/v/a.mp4", "in": 100, "out": 115}, {"src": "/v/m.mp3", "in": 0, "out": 30, "lane": "under"}]}
        stats = {"v": {"views": 1000, "avg_percent": 70, "gone": 0, "retention": curve(0.5, 1.0)}, "w": {"views": 1000, "gone": 0}}
        got = learning.published_examples({"s": "v"}, stats, lambda n: snapshot, lambda src: [first, second])
        values = {id(m): v for m, v in got}
        self.assertEqual(len(got), 4)
        self.assertGreater(values[id(first)], values[id(second)])
        flat = learning.published_examples({"s": "v"}, {**stats, "v": {**stats["v"], "retention": None}}, lambda n: snapshot, lambda src: [first, second])
        self.assertEqual(len(flat), 2)
        self.assertEqual(flat[0][1], flat[1][1])
