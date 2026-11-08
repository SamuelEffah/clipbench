"""Each song or sound in the Music panel has a small menu: make a no-vocals copy (songs only) and move to the Trash."""
import shutil
import subprocess
import unittest
from pathlib import Path

VOCALS = Path(__file__).resolve().parents[1] / "scripts/clipper_ui/vocals.js"


@unittest.skipUnless(shutil.which("node"), "node isn't installed")
class MusicMenuTests(unittest.TestCase):
    def run_node(self, script):
        source = VOCALS.read_text()
        code = source.split("const voxBusy", 1)[0] + "const voxBusy" + source.split("const voxBusy", 1)[1]
        result = subprocess.run(["node", "-e", r'''
const assert = require('node:assert/strict');
const calls = [], toasts = [];
let menu = null, project = {audio: [{id: 'x', file: 'f1'}, {id: 'y', file: 'f2'}]};
const state = {audioSel: 'x', get project() { return project; }, set project(v) { project = v; }};
const audioOf = () => project.audio;
let audioFiles = [], isSong = f => f.kind === 'song';
const api = async (url, method) => { calls.push(url); if (url.includes('bad')) throw new Error('nope'); return {ok: true}; };
const refreshAudio = async () => calls.push('refresh');
const changed = () => calls.push('changed');
const toast = m => toasts.push(m);
const paintMusic = () => {};
const openCtx = (x, y, items) => { menu = items; };
const document = {createElement: () => ({setAttribute() {}, getBoundingClientRect: () => ({right: 10, bottom: 10})})};
''' + code + script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_song_offers_no_vocals_and_trash_and_an_effect_only_trash(self):
        self.run_node(r'''
const song = {id: 'f1', name: 'Song', kind: 'song'}, fx = {id: 'f3', name: 'Pop', kind: 'sfx'};
audioFiles = [song, fx];
musicMenu(song, new Set(['Song'])).onclick({stopPropagation() {}});
assert.deepEqual(menu.filter(i => i !== '-').map(i => i.label), ['Make a copy with no vocals', 'Move to Trash']);
musicMenu(fx, new Set()).onclick({stopPropagation() {}});
assert.deepEqual(menu.map(i => i.label), ['Move to Trash']);
audioFiles = [song, {id: 'i', name: 'Song (instrumental)', kind: 'song'}];
musicMenu(song, new Set(audioFiles.map(f => f.name))).onclick({stopPropagation() {}});
assert.deepEqual(menu.map(i => i.label), ['Move to Trash'], 'already has a no-vocals copy');
''')

    def test_trashing_a_song_also_clears_it_from_this_timeline(self):
        self.run_node(r'''
(async () => {
  await deleteMusic({id: 'f1', name: 'Song'});
  assert.deepEqual(calls, ['/api/remove-audio/f1', 'changed', 'refresh']);
  assert.deepEqual(project.audio.map(a => a.id), ['y']);
  assert.equal(state.audioSel, null);
  assert.deepEqual(toasts, ['Song moved to the Trash']);
  calls.length = 0;
  await deleteMusic({id: 'bad', name: 'Gone'});
  assert.deepEqual(toasts.slice(1), ['nope'], 'a failure says why and changes nothing');
})().catch(e => { console.error(e); process.exitCode = 1; });
''')


if __name__ == "__main__":
    unittest.main()
