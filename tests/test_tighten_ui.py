import shutil
import subprocess
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "scripts" / "clipper_ui"

PRELUDE = r'''
const assert = require('assert');
const outLen = c => (c.out - c.in) / (c.speed || 1);
const TOUCH = 0.05;
const toasts = [];
const toast = m => toasts.push(m);
const calls = [];
let apiAnswer = () => ({pauses: []});
const api = async (path, method, body) => { calls.push([path, body]); return apiAnswer(body); };
const talk = (a, b, extra = {}) => ({clip: {src: "v", in: a, out: b, caption: "hi", words: [["hi", 0, 1]], ...extra}, found: {layout: "single"}, from: "c"});
'''


def run_js(body):
    source = (UI / "tighten.js").read_text()
    return subprocess.run(["node", "-e", PRELUDE + source + body], capture_output=True, text=True)


@unittest.skipUnless(shutil.which("node"), "Node required")
class CuttingPauses(unittest.TestCase):
    def check(self, body):
        result = run_js(body)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_short_within_length_is_left_as_it_is(self):
        self.check(r'''
const pieces = [talk(0, 30)];
assert.strictEqual(cutPauses(pieces, () => [[10, 11]], 40), pieces);
''')

    def test_the_longest_pauses_go_first_until_the_short_fits_and_each_cut_splits_the_piece(self):
        self.check(r'''
const out = cutPauses([talk(0, 42)], () => [[10, 11], [20, 20.5], [30, 31.5]], 40);
assert.deepEqual(out.map(p => [p.clip.in, p.clip.out]), [[0, 10], [11, 30], [31.5, 42]]);
assert.deepEqual(out.map(p => Boolean(p.pause)), [false, true, true]);
assert.equal(out[0].clip.caption, "hi");
assert.deepEqual(out.slice(1).map(p => [p.clip.caption, p.clip.words]), [["", null], ["", null]]);
assert.ok(out.every(p => p.from === "c" && p.found.layout === "single"));
''')

    def test_only_talk_is_tightened_so_a_webcam_over_gameplay_keeps_its_quiet(self):
        self.check(r'''
const cam = {clip: {src: "v", in: 0, out: 42}, found: {layout: "webcam"}};
const none = {clip: {src: "v", in: 0, out: 42}, found: {layout: "none"}};
assert.deepEqual(cutPauses([cam], () => [[10, 13]], 40), [cam]);
assert.deepEqual(cutPauses([none], () => [[10, 13]], 40), [none]);
''')

    def test_a_pause_at_an_edge_trims_the_piece_instead_of_leaving_a_sliver(self):
        self.check(r'''
const out = cutPauses([talk(0, 42)], () => [[0.1, 1.2], [41.5, 41.9]], 40);
assert.deepEqual(out.map(p => [p.clip.in, p.clip.out]), [[1.2, 41.5]]);
assert.equal(out[0].clip.caption, "hi");
assert.equal(Boolean(out[0].pause), false);
''')

    def test_a_few_words_between_a_pause_and_a_shot_change_are_kept(self):
        self.check(r'''
const out = cutPauses([talk(0, 43)], () => [[40.5, 41.55], [10, 12]], 40);
assert.deepEqual(out.map(p => [p.clip.in, p.clip.out]), [[0, 10], [12, 40.5], [41.55, 43]]);
''')

    def test_pauses_outside_a_piece_are_not_its_pauses(self):
        self.check(r'''
const out = cutPauses([talk(10, 52)], () => [[2, 5], [30, 31], [51, 53]], 40);
assert.deepEqual(out.map(p => [p.clip.in, p.clip.out]), [[10, 30], [31, 52]]);
''')

    def test_a_sped_up_clip_saves_less_running_time_per_pause(self):
        self.check(r'''
const out = cutPauses([talk(0, 84, {speed: 2})], () => [[10, 12], [40, 41]], 40);
assert.deepEqual(out.map(p => [p.clip.in, p.clip.out]), [[0, 10], [12, 40], [41, 84]]);
''')

    def test_pauses_spread_over_several_pieces_are_taken_from_the_longest_down(self):
        self.check(r'''
const a = talk(0, 20), b = {...talk(100, 123), clip: {...talk(100, 123).clip, caption: ""}};
const out = cutPauses([a, b], p => (p.clip.in === 0 ? [[5, 5.5]] : [[110, 112], [120, 120.6]]), 40);
assert.deepEqual(out.map(p => [p.clip.in, p.clip.out]), [[0, 5], [5.5, 20], [100, 110], [112, 120], [120.6, 123]]);
const fewer = cutPauses([a, b], p => (p.clip.in === 0 ? [[5, 5.5]] : [[110, 112], [120, 121.2]]), 40);
assert.deepEqual(fewer.map(p => [p.clip.in, p.clip.out]), [[0, 20], [100, 110], [112, 120], [121.2, 123]]);
''')


@unittest.skipUnless(shutil.which("node"), "Node required")
class AskingForPauses(unittest.TestCase):
    def check(self, body):
        result = run_js(body)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_nothing_is_asked_when_the_short_already_fits(self):
        self.check(r'''
(async () => {
  const lookup = await pausesFor([talk(0, 30)], [{src: "v", in: 0, out: 30}], 40);
  assert.deepEqual(calls, []);
  assert.deepEqual(lookup(talk(0, 30)), []);
})().catch(e => { console.error(e); process.exit(1); });
''')

    def test_only_spans_with_talk_are_asked_and_their_pauses_are_found_by_source(self):
        self.check(r'''
(async () => {
  apiAnswer = body => ({pauses: body.src === "v" ? [[3, 4]] : [[7, 8]]});
  const cam = {clip: {src: "g", in: 0, out: 30}, found: {layout: "webcam"}};
  const lookup = await pausesFor([talk(0, 30), cam], [{src: "v", in: 0, out: 30}, {src: "g", in: 0, out: 30}], 40);
  assert.deepEqual(calls.map(c => [c[0], c[1].src]), [["/api/pauses", "v"]]);
  assert.deepEqual(lookup(talk(0, 30)), [[3, 4]]);
  assert.deepEqual(lookup(cam), []);
})().catch(e => { console.error(e); process.exit(1); });
''')

    def test_a_failed_lookup_is_reported_and_leaves_the_tail_trim_to_do_its_work(self):
        self.check(r'''
(async () => {
  apiAnswer = () => { throw new Error("Could not read the sound"); };
  const lookup = await pausesFor([talk(0, 50)], [{src: "v", in: 0, out: 50}], 40);
  assert.deepEqual(lookup(talk(0, 50)), []);
  assert.deepEqual(toasts, ["Could not read the sound"]);
})().catch(e => { console.error(e); process.exit(1); });
''')


if __name__ == "__main__":
    unittest.main()
