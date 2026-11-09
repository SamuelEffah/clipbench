import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import suggest  # noqa: E402

UI = Path(__file__).resolve().parent.parent / "scripts" / "clipper_ui"
# Two exchanges 40 seconds apart, each about 16 seconds: too short alone, a Short together.
CUES = [
    (10.0, 14.0, "What are you doing?!"), (14.2, 19.0, "Stop. Right now!"), (19.2, 26.0, "I can't believe this is happening."),
    (66.0, 70.0, "Where did he go?"), (70.2, 75.0, "He was right here!"), (75.2, 82.0, "Nobody saw him leave at all."),
]
PEAKS = [100] * 20 * 120


class JoinedMoments(unittest.TestCase):
    def test_two_short_moments_near_each_other_are_offered_as_one_short_with_the_gap_cut_out(self):
        got = suggest.suggest(CUES, 120, [], PEAKS, 20, profile={"kind": "speech"})
        top = got[0]
        self.assertEqual(len(top["pieces"]), 2)
        self.assertAlmostEqual(top["pieces"][0][0], 9.75, places=2)
        self.assertAlmostEqual(top["pieces"][1][1], 82.4, places=2)
        self.assertTrue(suggest.SHORT_MIN <= top["length"] <= suggest.SHORT_MAX)
        self.assertIn("…", top["text"])
        self.assertEqual(top["in"], top["pieces"][0][0])
        self.assertEqual(top["out"], top["pieces"][1][1])
        self.assertEqual(set(top["parts"]), {"energy", "words", "hook"})
        self.assertNotIn("pieces", got[1])

    def test_the_joined_score_is_the_halves_before_their_length_penalty(self):
        a = {"in": 10, "out": 26, "text": "a", "score": 0.8 * suggest.length_fit(16), "why": "joke", "parts": {"hook": 80}}
        b = {"in": 66, "out": 82, "text": "b", "score": 0.4 * suggest.length_fit(16), "why": "reveal", "parts": {"hook": 20}}
        got = suggest.joined([a, b])
        self.assertEqual(len(got), 1)
        self.assertAlmostEqual(got[0]["score"], 0.6)
        self.assertEqual(got[0]["why"], "joke")
        self.assertEqual(got[0]["parts"], {"hook": 50})

    def test_no_join_when_apart_too_long_or_already_a_short_or_too_much_together(self):
        a = {"in": 10, "out": 26, "text": "a", "score": 0.5}
        self.assertEqual(suggest.joined([a, {"in": 200, "out": 216, "text": "b", "score": 0.5}]), [])
        self.assertEqual(suggest.joined([a, {"in": 66, "out": 100, "text": "b", "score": 0.5}]), [])
        self.assertEqual(suggest.joined([a, {"in": 66, "out": 94, "text": "b", "score": 0.5}]), [])
        self.assertEqual(suggest.joined([a, {"in": 20, "out": 40, "text": "b", "score": 0.5}]), [])
        self.assertEqual(suggest.joined([a, {"in": 66, "out": 82, "text": "", "score": 0.5}]), [])


PRELUDE = r'''
const assert = require('assert');
const state = {current: {id: "v", path: "/v.mp4"}, project: {clips: []}, sel: null, arrived: -1};
const cuts = []; const requestCut = c => cuts.push(c); let changes = 0; const changed = () => changes++; const paintSuggest = () => {};
'''


@unittest.skipUnless(shutil.which("node"), "Node required")
class JoinedInThePanel(unittest.TestCase):
    def run_js(self, body):
        source = (UI / "suggest.js").read_text().split("function suggestClip", 1)[1].split("function suggestionKey", 1)[0]
        result = subprocess.run(["node", "-e", PRELUDE + "function suggestClip" + source + body], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_joined_moment_becomes_one_clip_per_piece_in_order_and_counts_as_added_once_they_are_there(self):
        self.run_js(r'''
const joined = {in: 9.75, out: 82.4, pieces: [[9.75, 26.4], [65.75, 82.4]], length: 33.3};
const clips = suggestClips(joined);
assert.deepEqual(clips.map(c => [c.in, c.out]), [[9.75, 26.4], [65.75, 82.4]]);
assert.equal(suggestClips({in: 100, out: 130}).length, 1);
assert.ok(!suggestAdded(joined));
state.project.clips = clips;
assert.ok(suggestAdded(joined));
assert.ok(!suggestAdded({in: 9.75, out: 82.4, pieces: [[9.75, 26.4], [90, 100]]}));
''')


if __name__ == "__main__":
    unittest.main()
