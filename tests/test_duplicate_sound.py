"""A sound on the Short timeline can be duplicated: the copy keeps the trim, level and fades and lands right after the original."""
import shutil
import subprocess
import unittest
from pathlib import Path

AUDIO = Path(__file__).resolve().parents[1] / "scripts/clipper_ui/audio.js"


@unittest.skipUnless(shutil.which("node"), "node isn't installed")
class DuplicateSoundTests(unittest.TestCase):
    def test_the_copy_keeps_the_trim_and_sits_after_the_original(self):
        source = AUDIO.read_text()
        code = "function duplicateAudio(" + source.split("function duplicateAudio(", 1)[1].split("\nfunction selectAudio", 1)[0]
        script = r'''
const assert = require('node:assert/strict');
const a = {id: 'a1', file: 'f', label: 'Theme', kind: 'song', total: 90, start: 4, in: 12.5, dur: 8.25, volume: 0.6, fadeIn: 1, fadeOut: 2};
const state = {audioSel: 'a1', project: {audio: [a]}};
const audioOf = () => state.project.audio;
const newAudioId = () => 'a2';
const secs = v => `${v}s`;
const events = [];
const changed = () => events.push('changed');
const setTab = t => events.push('tab:' + t);
const toast = m => events.push(m);
const duplicateChosen = () => events.push('clips');
''' + code + r'''
duplicateAudio('a1');
assert.equal(state.project.audio.length, 2);
assert.deepEqual(state.project.audio[1], {...a, id: 'a2', start: 12.25});
assert.equal(state.project.audio[0], a, 'the original is untouched');
assert.equal(state.audioSel, 'a2', 'the copy is selected');
duplicateAudio('nope');
assert.equal(state.project.audio.length, 2);
duplicateSelected();
assert.equal(state.project.audio.length, 3, 'D duplicates the selected sound');
state.audioSel = null;
duplicateSelected();
assert.ok(events.includes('clips'), 'with no sound selected D still duplicates clips');
'''
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_sound_has_a_button_and_a_right_click_menu(self):
        source = AUDIO.read_text()
        self.assertIn("Duplicate this sound", source)
        self.assertIn("b.oncontextmenu", source)


if __name__ == "__main__":
    unittest.main()
