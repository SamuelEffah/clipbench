"""Voice only has to hold up in the editor, not just in the render: the preview plays the isolated wav in place of the
clip's own sound, a clip whose range changes is isolated again on its own, and the time it takes is said honestly."""
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import clipper  # noqa: E402
import voice_isolation  # noqa: E402

UI = Path(__file__).resolve().parents[1] / "scripts/clipper_ui"


class VoiceFileRouteTests(unittest.TestCase):
    def request(self, path):
        handler = object.__new__(clipper.Handler)
        handler.host_ok = lambda: True
        handler.path = path
        handler.headers = {}
        handler.wfile = io.BytesIO()
        handler.sent = {}
        handler.send_response = lambda status: setattr(handler, "status", status)
        handler.send_error = handler.send_response
        handler.send_header = lambda key, value: handler.sent.update({key: value})
        handler.end_headers = lambda: None
        handler.do_GET()
        return handler

    def test_a_saved_voice_is_served_as_a_wav_and_a_missing_one_is_not_found(self):
        with tempfile.TemporaryDirectory() as folder:
            target = voice_isolation.cached_path(folder, "/x/a.mkv", 1.0, 5.0)
            target.write_bytes(b"RIFFvoice")
            with mock.patch.object(clipper, "VOICE_DIR", Path(folder)):
                hit = self.request(f"/voice/{target.name}")
                self.assertEqual(hit.status, 200)
                self.assertEqual(hit.sent.get("Content-Type"), "audio/wav")
                self.assertEqual(hit.wfile.getvalue(), b"RIFFvoice")
                self.assertEqual(self.request("/voice/0123456789abcdef.wav").status, 404)


class VoiceJobTests(unittest.TestCase):
    def test_a_finished_job_says_where_the_voice_is(self):
        with tempfile.TemporaryDirectory() as folder:
            def fake_isolate(where, src, start, end, track=0):
                target = voice_isolation.cached_path(where, src, start, end, track)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"RIFF")
                return target
            with mock.patch.object(clipper, "VOICE_DIR", Path(folder)), mock.patch.object(clipper, "voice_jobs", {}), \
                    mock.patch.object(voice_isolation, "isolate", fake_isolate):
                job = clipper.start_voice("/x/a.mkv", 1.0, 5.0)
                for _ in range(50):
                    job = clipper.voice_jobs[job["id"]]
                    if job["state"] != "working":
                        break
                    import time
                    time.sleep(0.05)
                self.assertEqual(job["state"], "done")
                self.assertEqual(job["file"], f"/voice/{voice_isolation.cached_path(folder, '/x/a.mkv', 1.0, 5.0).name}")
                again = clipper.start_voice("/x/a.mkv", 1.0, 5.0)
                self.assertEqual((again["state"], again["file"]), ("done", job["file"]))

    def test_a_voice_being_made_is_known(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(voice_isolation.working(folder, "/x/a.mkv", 1.0, 5.0))
            key = str(voice_isolation.cached_path(folder, "/x/a.mkv", 1.0, 5.0).absolute())
            with mock.patch.dict(voice_isolation._pending, {key: object()}):
                self.assertTrue(voice_isolation.working(folder, "/x/a.mkv", 1.0, 5.0))
                self.assertFalse(voice_isolation.working(folder, "/x/a.mkv", 1.0, 5.5))


class VoiceRenderMessageTests(unittest.TestCase):
    def test_a_render_during_isolation_says_to_wait_rather_than_to_redo_it(self):
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder) / "a.mp4"
            src.write_bytes(b"video")
            project = {"clips": [{"src": str(src), "in": 1.0, "out": 5.0, "voice": True}]}
            with mock.patch.object(clipper, "VOICE_DIR", Path(folder) / "voice"):
                with mock.patch.object(voice_isolation, "working", return_value=True):
                    with self.assertRaisesRegex(ValueError, "still being isolated"):
                        clipper.export_cuts("v", project, directory=Path(folder))
                with mock.patch.object(voice_isolation, "working", return_value=False):
                    with self.assertRaisesRegex(ValueError, "isolated again"):
                        clipper.export_cuts("v", project, directory=Path(folder))


@unittest.skipUnless(shutil.which("node"), "node isn't installed")
class VoiceUiTests(unittest.TestCase):
    def run_node(self, script):
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_voice_clip_without_its_file_is_isolated_again_once_and_a_failure_is_not_retried(self):
        self.run_node(r'''
const assert = require('node:assert/strict');
const calls = [], toasts = [];
let renders = 0;
const state = {project: {name: 'p', clips: [
  {src: 'a.mp4', in: 1, out: 5, voice: true},
  {src: 'a.mp4', in: 7, out: 9, voice: true},
  {src: 'a.mp4', in: 20, out: 30, voice: false}]}};
const render = () => renders++;
const toast = m => toasts.push(m);
const setClipField = () => { throw new Error('an already voice-only clip must not be edited again (that would add an undo step)'); };
const changed = () => {};
const api = async (path, method, body) => {
  calls.push([path, method, body]);
  if (body.in === 7) return {id: 'bad', state: 'error', message: 'Voice isolation is not installed'};
  return {id: 'ok', state: 'done', file: `/voice/${body.in}.wav`};
};
const setTimeout = (fn) => { fn(); return 0; };
''' + (UI / "voice.js").read_text() + r'''
(async () => {
  ensureVoices();
  await new Promise(r => process.nextTick(r));
  await new Promise(r => process.nextTick(r));
  assert.equal(calls.length, 2, 'both voice clips were asked for, the plain one was not');
  assert.equal(voiceUrl(state.project.clips[0]), '/voice/1.wav');
  assert.equal(voiceUrl(state.project.clips[1]), null);
  assert.equal(voiceUrl(state.project.clips[2]), null, 'a clip with its original sound has no voice file');
  assert.ok(toasts.some(t => /not installed/.test(t)), 'a failure is told');
  ensureVoices();
  await new Promise(r => process.nextTick(r));
  assert.equal(calls.length, 2, 'a known file and a failed clip are left alone');
  assert.match(voiceEstimate({in: 10, out: 35.4}), /about 25s/);
})().catch(e => { console.error(e); process.exitCode = 1; });
''')

    def test_the_preview_hears_the_isolated_voice_in_step_with_the_picture(self):
        audio = (UI / "audio.js").read_text()
        code = "const voicePlayers" + audio.split("const voicePlayers", 1)[1].split("// ----- Dropping a sound", 1)[0]
        self.run_node(r'''
const assert = require('node:assert/strict');
const previewMuted = false;
const files = new Map([['a.mp4|1|5', '/voice/x.wav']]);
const voiceKey = c => `${c.src}|${c.in}|${c.out}`;
const voiceUrl = c => (c.voice && files.get(voiceKey(c))) || null;
const volumeOf = c => c.volume ?? 1, playVolume = c => volumeOf(c), baseOf = el => Number(el.dataset.base) || 0;
const tnow = el => el.currentTime + baseOf(el);
const setPlaybackValue = (t, k, v) => { if (t[k] !== v) t[k] = v; };
const made = [];
class Audio { constructor(src) { this.src = src; this.paused = true; this.currentTime = 0; made.push(this); }
  play() { this.paused = false; return Promise.resolve(); } pause() { this.paused = true; } }
const clip = {src: 'a.mp4', in: 1, out: 5, voice: true, volume: 0.8};
const state = {project: {clips: [clip]}};
const preview = {on: true, done: false, idx: 0};
const video = {dataset: {base: '1'}, currentTime: 2.5, paused: false, playbackRate: 1.5, muted: false};
const laneVids = [], lowNow = [];
''' + code + r'''
syncVoices();
assert.equal(made.length, 1);
const p = made[0];
assert.equal(p.src, '/voice/x.wav');
assert.equal(video.muted, true, 'the clip\'s own sound is muted while the voice plays');
assert.equal(p.currentTime, 2.5, 'wav time is source time past the clip\'s in point');
assert.equal(p.playbackRate, 1.5);
assert.equal(p.volume, 0.8);
assert.equal(p.paused, false);
video.currentTime = 2.6;
syncVoices();
assert.equal(made.length, 1, 'one player per clip');
video.paused = true;
syncVoices();
assert.equal(p.paused, true, 'the voice pauses with the picture');
clip.voice = false;
syncVoices();
assert.equal(video.muted, false, 'back to the original sound when the voice is dropped');
preview.on = false;
syncVoices();
assert.equal(p.paused, true);
''')


if __name__ == "__main__":
    unittest.main()
