import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class AudioIdLookupPerformance(unittest.TestCase):
    def test_stable_frames_reuse_ids_and_changed_lists_remove_players(self):
        audio = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/audio.js').read_text()
        mix = 'const soundPlayers' + audio.split('const soundPlayers', 1)[1].split('// ----- Dropping', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
const performance={now:()=>1000},video={paused:true},preview={on:false,elapsed:0},previewMuted=false;
let reads=0,items=Array.from({length:2000},(_,i)=>({get id(){reads++;return `id${i}`;},start:100,dur:10}));
const audioOf=()=>items;
''' + mix + r'''
syncSounds();reads=0;
for(let n=0;n<120;n++)syncSounds();
assert.ok(reads<=240000,`${reads} sound ID reads over 120 frames`);
let pauses=0;const player={pause(){pauses++;}};
soundPlayers.set('id0',player);soundPlayers.set('gone',player);
items=items.slice(1);syncSounds();assert.equal(soundPlayers.size,0);assert.equal(pauses,2);
// Appending to an existing list also invalidates the lookup.
items.push({id:'new',start:100,dur:10});soundPlayers.set('new',player);syncSounds();
assert.equal(soundPlayers.has('new'),true);
items=[];syncSounds();assert.equal(soundPlayers.size,0);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
