import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import clipper  # noqa: E402
import learning  # noqa: E402
import suggest  # noqa: E402
from store import Store  # noqa: E402

JOKE = {"text": "a line", "why": "joke", "parts": {"hook": 80, "energy": 70, "words": 65}}
QUIET = {"text": "b line", "why": "explanation", "parts": {"hook": 20, "energy": 15, "words": 30}}


class LessonsFromTheBench(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = Store(root / "bench.db")
        self.src = root / "episode.mp4"
        self.src.write_bytes(b"video")
        self.vid = clipper.video_id(self.src)
        (root / "proxy").mkdir()
        (root / "proxy" / f"{self.vid}.suggest.json").write_text(json.dumps({
            "state": "ready", "version": 1, "profile": {"kind": "speech"},
            "clips": [{"in": 10, "out": 40, "score": 0.5, **JOKE}, {"in": 100, "out": 130, "score": 0.6, **QUIET}]}))
        (root / "rendered").mkdir()
        (root / "rendered" / "monster.json").write_text(json.dumps({"clips": [{"src": str(self.src), "in": 12, "out": 38, "lane": "top"},
                                                                               {"src": str(self.src), "in": 102, "out": 128, "lane": "under"}]}))
        short = root / "shorts" / "003_monster"
        short.mkdir(parents=True)
        (short / "video.mp4").write_bytes(b"short")
        (short / "title.txt").write_text("Would you open the box?")
        patches = [mock.patch.object(clipper, "store", self.store), mock.patch.object(clipper, "PROXY_DIR", root / "proxy"),
                   mock.patch.object(clipper, "SNAPSHOT_DIR", root / "rendered"), mock.patch.object(clipper, "SHORT_DIR", root / "shorts"),
                   mock.patch.object(clipper, "registry", {self.vid: self.src}), mock.patch.object(clipper, "short_duration", lambda p: 30.0),
                   mock.patch.object(clipper, "_lessons", None)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        stub = mock.patch.object(clipper, "publisher", mock.Mock(state=lambda name: {"state": "none"}, channel=lambda: {}))
        stub.start()
        self.addCleanup(stub.stop)

    def test_a_short_posted_by_hand_teaches_through_its_title_and_only_its_top_lane(self):
        now = time.time()
        self.store.save_channel_videos([{"video_id": "vidAAAAAAAA1", "title": "Would you open the box?", "published_at": "2026-10-20T15:04:59Z"}], now)
        self.store.save_video_stats({"vidAAAAAAAA1": {"views": 1337, "likes": 1, "comments": 0}, "other": {"views": 100, "likes": 0, "comments": 0}}, now)
        self.store.save_video_analytics({"vidAAAAAAAA1": {"avg_duration": 30, "avg_percent": 87.19, "retention": [1.0 - i / 200 for i in range(100)]}}, now)
        got = clipper.current_lessons()
        self.assertIn("why:joke", got)
        self.assertNotIn("why:explanation", got)
        self.assertGreater(got["why:joke"][0], 0)
        self.assertEqual(got["why:joke"][1], 1)
        self.assertEqual(got["hook:high"][1], 2, "the clip's opening teaches the hook on its own")
        self.assertIn("profile:speech", got)

    def test_decisions_teach_too_and_the_lessons_are_kept_for_a_minute(self):
        self.store.review_suggestion(self.vid, 100, 130, "skip", QUIET)
        got = clipper.current_lessons()
        self.assertEqual(got["why:explanation"], (learning.SKIP_VALUE, 1))
        self.store.review_suggestion(self.vid, 10, 40, "keep", JOKE)
        self.assertNotIn("why:joke", clipper.current_lessons())
        clipper._lessons = None
        self.assertIn("why:joke", clipper.current_lessons())

    def test_a_decision_made_in_the_app_teaches_at_once(self):
        clipper.current_lessons()
        clipper.review_suggestion(self.vid, {"in": 10, "out": 40, "decision": "keep", "moment": JOKE})
        self.assertIn("why:joke", clipper.current_lessons())

    def test_saved_suggestions_come_back_reranked_with_the_reason(self):
        for _ in range(8):
            self.store.review_suggestion(self.vid, 100 + _, 130, "skip", QUIET)
        cache = Path(self.tmp.name) / "proxy" / f"{self.vid}.suggest.json"
        cache.write_text(json.dumps({"state": "ready", "version": suggest.VERSION, "profile": {"kind": "speech"},
                                     "clips": [{"in": 100, "out": 130, "score": 0.6, **QUIET}, {"in": 10, "out": 40, "score": 0.55, **JOKE}]}))
        with mock.patch.object(clipper, "suggest_jobs", {}):
            got = clipper.get_suggest(self.vid)
        self.assertEqual([c["in"] for c in got["clips"]], [10, 100])
        self.assertEqual(got["clips"][1]["learned"]["note"], "explanations did poorly before")
        self.assertNotIn("learned", got["clips"][0])
        self.assertEqual(json.loads(cache.read_text())["clips"][0]["in"], 100)

    def test_a_search_still_running_hands_over_what_it_has_scored_reranked(self):
        for _ in range(8):
            self.store.review_suggestion(self.vid, 100 + _, 130, "skip", QUIET)
        job = {"state": "working", "pct": 50, "model": "qwen3", "profile": {"kind": "speech"},
               "clips": [{"in": 100, "out": 130, "score": 0.6, **QUIET}, {"in": 10, "out": 40, "score": 0.55, **JOKE}]}
        with mock.patch.object(clipper, "suggest_jobs", {self.vid: job}):
            got = clipper.get_suggest(self.vid)
        self.assertEqual(got["state"], "working")
        self.assertEqual([c["in"] for c in got["clips"]], [10, 100])
        self.assertEqual(job["clips"][0]["in"], 100, "the running job keeps its own order")

    def test_a_broken_snapshot_or_missing_cache_teaches_nothing_and_raises_nothing(self):
        (Path(self.tmp.name) / "rendered" / "monster.json").write_text("{bad")
        self.store.save_channel_videos([{"video_id": "v", "title": "Would you open the box?", "published_at": "x"}], 1)
        self.store.save_video_stats({"v": {"views": 10, "likes": 0, "comments": 0}}, 1)
        self.assertEqual(clipper.current_lessons(), {})
        self.assertEqual(clipper.saved_suggestions("/nowhere.mp4"), [])


class MeasuringARender(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.src = root / "episode.mkv"
        self.src.write_bytes(b"video")
        self.vid = clipper.video_id(self.src)
        (root / "rendered").mkdir()
        (root / "proxy").mkdir()
        cues = [(10.0, 13.0, "What are you doing?!"), (13.2, 16.0, "Stop. Right now!"), (40.0, 44.0, "Later on.")]
        patches = [mock.patch.object(clipper, "SNAPSHOT_DIR", root / "rendered"), mock.patch.object(clipper, "PROXY_DIR", root / "proxy"),
                   mock.patch.object(clipper, "registry", {self.vid: self.src}), mock.patch.object(clipper, "dialogue_cues", lambda src: cues),
                   mock.patch.object(clipper, "load_wave", lambda vid: {"peaks": [10] * 2000, "per_sec": 20}),
                   mock.patch.object(clipper, "probe", lambda src: {"duration": 100.0}),
                   mock.patch.object(clipper.clip_motion, "compute", side_effect=AssertionError("motion must not be measured at render time"))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.project = {"clips": [{"src": str(self.src), "in": 9.5, "out": 20.0, "lane": "top"}, {"src": str(self.src), "in": 9.5, "out": 20.0, "lane": "under"},
                                  {"src": "/gone/other.mp4", "in": 1, "out": 5, "lane": "top"}, {"src": str(self.src), "in": 38.0, "out": 50.0}]}

    def test_each_top_lane_clip_of_a_known_video_gets_its_moment_written_into_the_snapshot(self):
        (Path(self.tmp.name) / "rendered" / "ep.json").write_text(json.dumps(self.project))
        clipper.describe_render("ep", self.project)
        saved = json.loads((Path(self.tmp.name) / "rendered" / "ep.json").read_text())
        self.assertEqual(saved["clips"], self.project["clips"])
        self.assertEqual([(m["src"], m["in"], m["out"]) for m in saved["moments"]], [(str(self.src), 9.5, 20.0), (str(self.src), 38.0, 50.0)])
        self.assertEqual(saved["moments"][0]["text"], "What are you doing?! Stop. Right now!")
        self.assertEqual(set(saved["moments"][0]["parts"]), {"hook", "energy", "words"})
        self.assertIn("profile", saved["moments"][0])
        self.assertEqual(learning.measured_moment(self.project["clips"][3], saved)["text"], "Later on.")

    def test_a_video_that_cannot_be_read_leaves_the_snapshot_as_it_was(self):
        (Path(self.tmp.name) / "rendered" / "ep.json").write_text(json.dumps(self.project))
        with mock.patch.object(clipper, "dialogue_cues", side_effect=OSError("gone")):
            clipper.describe_render("ep", self.project)
        self.assertNotIn("moments", json.loads((Path(self.tmp.name) / "rendered" / "ep.json").read_text()))


UI = Path(__file__).resolve().parent.parent / "scripts" / "clipper_ui"


@unittest.skipUnless(__import__("shutil").which("node"), "Node required")
class LearnedLine(unittest.TestCase):
    def test_the_card_says_what_was_learned_and_how_far_it_moved(self):
        source = (UI / "suggest.js").read_text().split("const learnedNote", 1)[1].split("\n", 1)[0]
        script = ("const assert = require('assert'); const esc = s => String(s).replace(/</g, '&lt;');\nconst learnedNote" + source + "\n"
                  "assert.equal(learnedNote(undefined), '');\nassert.equal(learnedNote({delta: 0, note: ''}), '');\n"
                  "const up = learnedNote({delta: 12, note: 'jokes did well before'});\n"
                  "assert.ok(up.includes('jokes did well before, +12%'), up); assert.ok(up.includes('Moved up 12%'), up);\n"
                  "const down = learnedNote({delta: -8, note: 'quiet <moments> did poorly before'});\n"
                  "assert.ok(down.includes('quiet &lt;moments> did poorly before, -8%'), down); assert.ok(down.includes('Moved down 8%'), down);\n")
        result = __import__("subprocess").run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
