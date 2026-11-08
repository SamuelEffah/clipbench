"""The preview plays a clip from whatever is already playable, its own cut file or the source, the moment it is asked.
The cut is still requested in the background for next time; nothing waits on it unless there is nothing else to play.
Until this, every trim or drop froze the playhead for the cut's whole encode (six seconds measured)."""
import shutil
import subprocess
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "scripts/clipper_ui/app.js"


def slice_of(source, start, stop):
    return start + source.split(start, 1)[1].split(stop, 1)[0]


def preview_range_code():
    source = APP.read_text()
    return (slice_of(source, "function clipFile(c) {", "\nlet saveTimer")
            + "\n" + slice_of(source, "async function previewRange(", "\nfunction preloadPreview"))


STUBS = r'''
const assert = require('node:assert/strict');
const events = [];
const preview = {live: false, hold: false, idx: 0};
const state = {clipStop: null, project: {clips: []}};
const previewMuted = false;
const cutIds = new Map(), cutJobs = new Map(), cutFailed = new Map(), CUT_RETRY_MS = 30000;
const cutKey = c => `${c.src}|${c.in.toFixed(3)}|${c.out.toFixed(3)}`;
let cutResolve;
const requestCut = () => { events.push('requestCut'); return new Promise(r => { cutResolve = r; }); };
const byPath = () => library;
let spareEl = {dataset: {}, readyState: 0};
const spare = () => spareEl;
const speedAt = () => 1, volumeOf = () => 1, playVolume = () => 1, leaveAt = c => c.out, baseOf = el => Number(el.dataset.base) || 0;
const playTransition = () => {}, toast = m => events.push('toast:' + m);
const loadFileInto = (el, file, then) => { events.push('load:' + file.url); el.dataset.id = file.id; el.dataset.base = file.base; el.readyState = 1; el.onready = then; };
const player = id => ({dataset: {id, base: '0'}, readyState: 1, paused: true, currentTime: 0,
  play() { events.push('play@' + this.currentTime); this.paused = false; return Promise.resolve(); }, pause() { this.paused = true; }});
let video = player('');
const swapTo = el => { events.push('swap'); video = el; };
'''


@unittest.skipUnless(shutil.which("node"), "node isn't installed")
class PreviewStartsNowTests(unittest.TestCase):
    def run_node(self, script):
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_ready_source_plays_at_once_while_the_cut_is_still_being_made(self):
        self.run_node(STUBS + "let library = {id: 'v1', ready: true};\n" + preview_range_code() + r'''
(async () => {
  video.dataset.id = 'v1';
  const clip = {src: '/w/a.mp4', in: 12, out: 20};
  const started = previewRange(clip, () => {}, () => true);
  await Promise.resolve(); await Promise.resolve();
  assert.equal(preview.live, true, 'the playhead is live before the cut exists');
  assert.deepEqual(events, ['requestCut', 'play@12'], 'played from the source, cut requested in the background');
  await started;
})().catch(e => { console.error(e); process.exitCode = 1; });
''')

    def test_a_saved_cut_is_preferred_when_it_already_exists(self):
        self.run_node(STUBS + "let library = {id: 'v1', ready: true};\n" + preview_range_code() + r'''
(async () => {
  const clip = {src: '/w/a.mp4', in: 12, out: 20};
  cutIds.set(cutKey(clip), 'c1');
  await previewRange(clip, () => {}, () => true);
  assert.deepEqual(events, ['load:/cut/c1.mp4']);
  video.onready();
  assert.deepEqual(events.slice(1), ['play@0'], 'a cut file starts at its own beginning');
})().catch(e => { console.error(e); process.exitCode = 1; });
''')

    def test_a_player_already_on_the_clips_source_keeps_it_rather_than_loading_the_cut(self):
        # Scrubbing across a cut must not swap files on every crossing; what is loaded and can show the clip is used.
        self.run_node(STUBS + "let library = {id: 'v1', ready: true};\n" + preview_range_code() + r'''
(async () => {
  const clip = {src: '/w/a.mp4', in: 12, out: 20};
  cutIds.set(cutKey(clip), 'c1');
  video = player('v1');
  await previewRange(clip, () => {}, () => true, 14);
  assert.deepEqual(events, ['requestCut', 'play@14'], 'no load, no swap: the source in the player shows this clip, the cut is only warmed');
})().catch(e => { console.error(e); process.exitCode = 1; });
''')

    def test_the_spare_player_holding_the_clips_file_is_shown_instead_of_loading_it_again(self):
        self.run_node(STUBS + "let library = {id: 'v1', ready: true};\n" + preview_range_code() + r'''
(async () => {
  const clip = {src: '/w/a.mp4', in: 12, out: 20};
  cutIds.set(cutKey(clip), 'c1');
  video = player('v2');
  spareEl = player('cut:c1');
  spareEl.dataset.base = '12';
  await previewRange(clip, () => {}, () => true, 14);
  assert.deepEqual(events, ['requestCut', 'swap', 'play@2'], 'the spare takes over at the right moment of the cut file');
})().catch(e => { console.error(e); process.exitCode = 1; });
''')

    def test_a_lane_player_on_the_clips_source_is_not_reloaded_for_its_cut(self):
        source = APP.read_text()
        code = slice_of(source, "function fileLoadedIn(", "\nasync function clipFileSoon") + "\n" + slice_of(source, "function syncLane(", "\n// Where each lane sits")
        self.run_node(r'''
const assert = require('node:assert/strict');
const clip = {src: '/w/a.mp4', in: 12, out: 20, lane: 'bottom'};
const state = {clipStop: null, project: {clips: [clip]}};
const preview = {elapsed: 3};
const previewMuted = false;
const cutIds = new Map([['/w/a.mp4|12.000|20.000', 'c1']]);
const cutKey = c => `${c.src}|${c.in.toFixed(3)}|${c.out.toFixed(3)}`;
const byPath = () => ({id: 'v1', ready: true});
const laneAt = () => ({clip, pos: 3, held: false});
const clipFile = () => ({id: 'cut:c1', url: '/cut/c1.mp4', base: 12});
const volumeOf = () => 1, playVolume = () => 1, speedOf = () => 1, movingLen = c => c.out - c.in, baseOf = el => Number(el.dataset.base) || 0;
const tnow = el => el.currentTime + baseOf(el);
const setPlaybackValue = (t, k, v) => { if (t[k] !== v) t[k] = v; };
const video = {paused: false};
const el = {dataset: {id: 'v1', base: '0'}, readyState: 2, paused: true, currentTime: 15, set src(v) { throw new Error('reloaded ' + v); }, play() { this.paused = false; return Promise.resolve(); }, pause() { this.paused = true; }};
''' + code + r'''
syncLane(el, 'bottom');
assert.equal(el.paused, false, 'the lane keeps playing from the source it already has');
''')

    def test_with_nothing_playable_it_waits_for_the_cut(self):
        self.run_node(STUBS + "let library = {id: 'v1', ready: false};\n" + preview_range_code() + r'''
(async () => {
  const clip = {src: '/w/a.mp4', in: 12, out: 20};
  const started = previewRange(clip, () => {}, () => true);
  await Promise.resolve(); await Promise.resolve();
  assert.equal(preview.live, false);
  assert.ok(!events.some(e => e.startsWith('play')), 'nothing to play yet');
  cutIds.set(cutKey(clip), 'c1');
  cutResolve('c1');
  await started;
  assert.ok(events.includes('load:/cut/c1.mp4'), events);
})().catch(e => { console.error(e); process.exitCode = 1; });
''')


@unittest.skipUnless(shutil.which("node"), "node isn't installed")
class ClipSwitchRenderTests(unittest.TestCase):
    def test_a_clip_switch_in_the_short_station_does_not_rebuild_the_page(self):
        source = APP.read_text()
        code = slice_of(source, "function playPreviewClip(", "\nfunction openPreview")
        script = r'''
const assert = require('node:assert/strict');
let renders = 0;
const render = () => renders++;
const preview = {run: 1, on: true, idx: 0, live: true};
const state = {mode: 'short', sel: 0, project: {clips: [{src: 'a', in: 0, out: 1}, {src: 'b', in: 0, out: 1}]}};
const video = {pause() {}};
const nextTop = i => i + 1;
const previewRange = () => {};
const setTimeout = () => {};
''' + code + r'''
playPreviewClip(1, 1);
assert.equal(renders, 0, 'the Short station paints the playing clip every frame already');
state.mode = 'clip';
playPreviewClip(1, 1);
assert.equal(renders, 1, 'the clip station still follows the selection');
assert.equal(state.sel, 1);
'''
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
