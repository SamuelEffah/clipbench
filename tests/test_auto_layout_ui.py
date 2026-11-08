import shutil
import subprocess
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "scripts" / "clipper_ui"

PRELUDE = r'''
const assert = require('assert');
const clamp01 = v => Math.min(1, Math.max(0, v));
const LANES = ["top", "bottom", "third", "fourth"];
const isTop = c => (c.lane || "top") === "top";
const pictureIn = (clip, size, cell, pan) => {
  const [vw, vh] = size, [W, H] = cell;
  const r = Math.max(W / vw, H / vh), w = vw * r, h = vh * r;
  return {W, H, w, h, fill: true, x: (W - w) * pan, y: (H - h) * pan};
};
'''


def run_js(body):
    source = (UI / "autolayout.js").read_text()
    source = source[source.index("const MAX_AUTO_ZOOM"):source.index("const autoBtn")]
    result = subprocess.run(["node", "-e", PRELUDE + source + body], capture_output=True, text=True)
    return result


@unittest.skipUnless(shutil.which("node"), "Node required")
class AutoLayoutLogic(unittest.TestCase):
    def check(self, body):
        result = run_js(body)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_webcam_crop_keeps_its_window_inside_the_webcam(self):
        self.check(r'''
const out = rectFor({}, {x: 0, y: 0.6, w: 0.3, h: 0.4}, [1920, 1080], [1080, 960]);
assert.equal(out.fit, "fill");
assert.ok(out.zoom > 1.5 && out.zoom <= 4, out.zoom);
const pic = pictureIn({}, [1920, 1080], [1080, 960], out.pan);
const winW = pic.W / out.zoom / pic.w, winH = pic.H / out.zoom / pic.h;
assert.ok(winW <= 0.3 + 1e-6 && winH <= 0.4 + 1e-6, `${winW} ${winH}`);
const left = (pic.x * -1 + (pic.W - pic.W / out.zoom) * out.zx) / pic.w;
const top = (pic.y * -1 + (pic.H - pic.H / out.zoom) * out.zy) / pic.h;
assert.ok(left >= -1e-3 && left + winW <= 0.3 + 1e-3, `left ${left}`);
assert.ok(top >= 0.6 - 1e-3 && top + winH <= 1 + 1e-3, `top ${top}`);
''')

    def test_a_clip_is_cut_into_one_piece_per_stretch_and_only_the_first_keeps_the_caption(self):
        self.check(r'''
const clip = {src: "a", in: 5, out: 35, caption: "hi", words: [1]};
const found = {layout: "people", faces: [], segments: [{start: 5, end: 10, layout: "people"}, {start: 10, end: 35, layout: "single"}]};
const pieces = piecesOf(clip, found);
assert.deepEqual(pieces.map(p => [p.clip.in, p.clip.out]), [[5, 10], [10, 35]]);
assert.equal(pieces[0].clip.caption, "hi");
assert.equal(pieces[1].clip.caption, "");
assert.equal(pieces[1].found.layout, "single");
''')

    def test_a_clip_without_segments_stays_whole(self):
        self.check(r'''
const pieces = piecesOf({src: "a", in: 1, out: 4}, {layout: "none", faces: []});
assert.equal(pieces.length, 1);
assert.deepEqual([pieces[0].clip.in, pieces[0].clip.out], [1, 4]);
''')

    def test_stacked_lanes_are_chosen_when_most_of_the_time_wants_them(self):
        self.check(r'''
const piece = (layout, len, faces = []) => ({clip: {in: 0, out: len}, found: {layout, faces}});
assert.equal(templateFor([piece("webcam", 10), piece("single", 4)]), "split");
assert.equal(templateFor([piece("webcam", 4), piece("single", 10)]), "full");
assert.equal(templateFor([piece("people", 10, [1, 2, 3])]), "three");
assert.equal(templateFor([piece("people", 10, [1, 2, 3, 4])]), "four");
assert.equal(templateFor([piece("none", 10)]), "full");
''')

    def test_a_webcam_lane_is_sized_to_the_webcam_within_30_and_42_percent_and_people_get_half(self):
        self.check(r'''
const canvasOf = () => [1080, 1920];
const cam = {layout: "webcam", webcam: {x: 0, y: 0.6, w: 0.295, h: 0.39}, width: 1920, height: 1080};
const piece = (found, len = 10) => ({clip: {in: 0, out: len}, found});
const share = topShare([piece(cam)], "split");
assert.ok(share >= 0.3 && share <= 0.42, share);
const wide = {...cam, webcam: {x: 0, y: 0.8, w: 0.5, h: 0.2}};
assert.equal(topShare([piece(wide)], "split"), 0.3);
assert.equal(topShare([piece(cam), piece({layout: "people"})], "split"), 0.5);
assert.equal(topShare([piece(cam)], "full"), 0.5);
assert.equal(topShare([piece({layout: "people"})], "split"), 0.5);
''')

    def test_the_area_beside_a_webcam_is_the_side_it_leaves(self):
        self.check(r'''
assert.deepEqual(besideCam({x: 0, y: 0.6, w: 0.3, h: 0.4}), {x: 0.3, y: 0, w: 0.7, h: 1});
const right = besideCam({x: 0.7, y: 0, w: 0.3, h: 0.4});
assert.deepEqual([right.x, right.y, right.w, right.h], [0, 0, 0.7, 1]);
''')

    def test_the_gameplay_lane_frames_the_area_beside_the_webcam_without_it(self):
        self.check(r'''
const canvasOf = () => [1080, 1920];
const cellOf = () => [1080, 1114];
const found = {layout: "webcam", webcam: {x: 0, y: 0.6, w: 0.295, h: 0.39}, width: 1920, height: 1080, faces: []};
const plans = lanePlan({src: "a", in: 0, out: 5}, found, 2);
const game = plans[1];
assert.equal(game.fit, "fill");
const pic = pictureIn({}, [1920, 1080], [1080, 1114], game.pan);
const left = (-pic.x + (pic.W - pic.W / game.zoom) * (game.zoom > 1 ? game.zx : 0)) / pic.w;
const seen = pic.W / game.zoom / pic.w;
assert.ok(left >= 0.295 - 1e-3, `left ${left}`);
assert.ok(left + seen <= 1 + 1e-3);
''')

    def test_a_short_over_forty_seconds_is_trimmed_on_its_last_piece(self):
        self.check(r'''
const piece = (a, b) => ({clip: {src: "x", in: a, out: b}});
const len = c => c.out - c.in;
const out = fitLength([piece(0, 25), piece(25, 50), piece(50, 80)], 40, len);
assert.equal(out.length, 2);
assert.deepEqual([out[0].clip.in, out[0].clip.out], [0, 25]);
assert.deepEqual([out[1].clip.in, out[1].clip.out], [25, 40]);
''')

    def test_a_short_under_forty_seconds_is_left_alone(self):
        self.check(r'''
const piece = (a, b) => ({clip: {src: "x", in: a, out: b}});
const len = c => c.out - c.in;
const list = [piece(0, 10), piece(10, 30)];
assert.deepEqual(fitLength(list, 40, len).map(p => p.clip.out), [10, 30]);
assert.equal(fitLength([piece(0, 40)], 40, len).length, 1);
''')

    def test_trimming_keeps_what_a_piece_carries(self):
        self.check(r'''
const out = fitLength([{clip: {src: "x", in: 5, out: 65, caption: "hi"}, from: "c", found: {layout: "single"}}], 40, c => c.out - c.in);
assert.equal(out[0].clip.out, 45);
assert.equal(out[0].clip.caption, "hi");
assert.equal(out[0].from, "c");
assert.equal(out[0].found.layout, "single");
''')

    def test_touching_clips_from_one_video_are_looked_at_as_one_span(self):
        self.check(r"""
const spans = spansOf([{src: "a", in: 0, out: 7}, {src: "a", in: 7, out: 15.01}, {src: "b", in: 0, out: 15.01}, {src: "a", in: 20, out: 25}]);
assert.deepEqual(spans.map(s => [s.src, s.in, s.out, s.clips.length]), [["a", 0, 15.01, 2], ["b", 0, 15.01, 1], ["a", 20, 25, 1]]);
assert.deepEqual(spansOf([]), []);
assert.equal(spansOf([{src: "a", in: 0, out: 100}, {src: "a", in: 100, out: 200}]).length, 2);
""")

    def test_a_span_answer_is_cut_down_to_each_clip_and_describes_its_longest_stretch(self):
        self.check(r"""
const found = {layout: "webcam", webcam: {x: 0}, faces: [], width: 1920, height: 1080, segments: [
  {start: 0, end: 10, layout: "webcam", webcam: {x: 0}, faces: []}, {start: 10, end: 15, layout: "single", webcam: null, faces: [{x: 0.5}]}]};
const a = foundFor({in: 0, out: 7}, found);
assert.deepEqual(a.segments.map(s => [s.start, s.end]), [[0, 7]]);
assert.equal(a.layout, "webcam");
assert.equal(a.width, 1920);
const b = foundFor({in: 7, out: 15}, found);
assert.deepEqual(b.segments.map(s => [s.start, s.end]), [[7, 10], [10, 15]]);
assert.equal(b.layout, "single");
assert.deepEqual(b.faces, [{x: 0.5}]);
assert.equal(foundFor({in: 7, out: 12}, found).layout, "webcam");
assert.deepEqual(foundFor({in: 9.99, out: 15}, found).segments.map(s => [s.start, s.end]), [[9.99, 15]]);
""")

    def test_the_summary_counts_cuts_within_clips_not_the_clips_themselves(self):
        self.check(r"""
const cam = {layout: "webcam", faces: []};
const a = {src: "a"}, b = {src: "b"};
assert.equal(describeLayout([{clip: {}, found: cam, from: a}, {clip: {}, found: cam, from: b}], "split"), "Webcam on top, gameplay below");
assert.equal(describeLayout([{clip: {}, found: cam, from: a}, {clip: {}, found: cam, from: a}], "split"), "Webcam on top, gameplay below, 1 cut where the shots change");
assert.equal(describeLayout([{clip: {}, found: cam, from: a}, {clip: {}, found: cam, from: a}, {clip: {}, found: cam, from: a}], "split"), "Webcam on top, gameplay below, 2 cuts where the shots change");
""")

    def test_a_single_person_is_followed_when_the_face_was_seen_over_time(self):
        self.check(r"""
const reframeFor = (clip, face, size, cell, track) => ({pan: 0.5, zoom: 2, zx: 0.1, zy: 0.2, track: track.map(s => [s.t, s.x, s.y])});
const clip = {src: "a", in: 0, out: 5, fit: "fit"};
const seen = {found: true, face: {x: 0.5, y: 0.4, w: 0.1, h: 0.2}, width: 1920, height: 1080, track: [{t: 0, x: 0.5, y: 0.4}, {t: 2, x: 0.6, y: 0.4}]};
const plan = followedPlan(clip, seen, [1080, 1920]);
assert.equal(plan.fit, "fill");
assert.equal(plan.tracking, true);
assert.equal(plan.track.length, 2);
assert.equal(followedPlan(clip, {found: false}, [1080, 1920]), null);
assert.equal(followedPlan(clip, null, [1080, 1920]), null);
assert.equal(followedPlan(clip, {...seen, track: [{t: 0, x: 0.5, y: 0.4}]}, [1080, 1920]).tracking, false);
""")

    def test_spans_looked_at_before_a_cam_was_found_are_asked_again_once_the_server_remembers_it(self):
        self.check(r"""
const spans = [{src: "a", in: 0, out: 15}, {src: "b", in: 0, out: 12}, {src: "c", in: 0, out: 9}, {src: "d", in: 0, out: 9}];
const cam = {layout: "webcam", guessed: false, webcam: {x: 0, y: 0.6, w: 0.29, h: 0.4}};
const first = [{layout: "single"}, {layout: "webcam", guessed: true, webcam: {x: 0, y: 0.5, w: 0.2, h: 0.5}}, cam, {layout: "none"}];
const asked = [];
const again = {layout: "webcam", remembered: true, webcam: cam.webcam};
(async () => {
  const out = await askAgain(spans, first, span => { asked.push(span.src); return Promise.resolve(again); });
  assert.deepEqual(asked, ["a", "b"]);
  assert.deepEqual(out.map(a => a.layout), ["webcam", "webcam", "webcam", "none"]);
  assert.strictEqual(out[2], cam);
  assert.strictEqual(first[0].layout, "single");
  const none = await askAgain(spans, [{layout: "single"}, {layout: "none"}], () => { throw new Error("asked"); });
  assert.equal(none.length, 2);
  const kept = await askAgain(spans.slice(0, 2), [cam, {layout: "single"}], () => { throw new Error("asked"); });
  assert.strictEqual(kept[0], cam);
})().catch(err => { console.error(err); process.exit(1); });
""")

    def test_a_guessed_cam_takes_the_border_found_cam_of_another_clip_of_the_stream_that_holds_its_face(self):
        self.check(r"""
const rect = {x: 0, y: 0.6, w: 0.29, h: 0.4};
const precise = {layout: "webcam", guessed: false, webcam: rect, width: 1920, height: 1080, faces: [{x: 0.1, y: 0.7, w: 0.1, h: 0.2}], segments: [{start: 0, end: 5, layout: "webcam", guessed: false, webcam: rect}]};
const guess = {x: 0, y: 0.5, w: 0.22, h: 0.5};
const guessed = {layout: "webcam", guessed: true, webcam: guess, width: 1920, height: 1080, faces: [{x: 0.13, y: 0.69, w: 0.1, h: 0.2}], segments: [{start: 10, end: 15, layout: "webcam", guessed: true, webcam: guess}]};
const out = adoptCam(guessed, [precise, guessed]);
assert.deepEqual(out.webcam, rect);
assert.equal(out.guessed, false);
assert.deepEqual(out.segments[0].webcam, rect);
assert.deepEqual(adoptCam(guessed, [{...precise, webcam: {x: 0.7, y: 0, w: 0.3, h: 0.4}}]).webcam, guess);
assert.deepEqual(adoptCam(guessed, [{...precise, width: 1280, height: 720}]).webcam, guess);
assert.deepEqual(adoptCam(guessed, [guessed]).webcam, guess);
assert.strictEqual(adoptCam(precise, [guessed]), precise);
""")

    def test_a_companion_is_a_lane_clip_repeating_a_top_clip(self):
        self.check(r'''
const tops = [{src: "a", in: 1, out: 5, lane: "top"}];
assert.equal(isCompanion({src: "a", in: 1, out: 5, lane: "bottom"}, tops), true);
assert.equal(isCompanion({src: "a", in: 1, out: 6, lane: "bottom"}, tops), false);
assert.equal(isCompanion({src: "a", in: 1, out: 5, lane: "top"}, tops), false);
''')


if __name__ == "__main__":
    unittest.main()
