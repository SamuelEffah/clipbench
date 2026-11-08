import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class AudioSyncPerformance(unittest.TestCase):
    def test_stable_mix_skips_media_writes_and_preserves_playback_transitions(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        app = (ui / 'app.js').read_text()
        helper = 'function setPlaybackValue(' + app.split('function setPlaybackValue(', 1)[1].split('\nfunction placePlayhead', 1)[0]
        audio = (ui / 'audio.js').read_text()
        mix = 'const soundPlayers' + audio.split('const soundPlayers', 1)[1].split('// ----- Dropping', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let writes=0,pauses=0,plays=0,clock=1000,previewMuted=false;
const performance={now:()=>clock};
const preview={on:true,done:false,live:true,elapsed:2},video={paused:false};
let items=[{id:'song',file:'file',kind:'song',start:0,dur:10,in:3,volume:1}];
const audioOf=()=>items;
class Audio {
 constructor(url) {return new Proxy({url,paused:true,currentTime:0,volume:1,muted:false,
  pause(){pauses++;this.paused=true;},play(){plays++;this.paused=false;return Promise.resolve();}},
  {set(t,k,v){if(['currentTime','volume','muted'].includes(k))writes++;t[k]=v;return true;}});}
}
''' + helper + mix + r'''
syncSounds();const song=soundPlayers.get('song');
assert.equal(song.currentTime,5);assert.equal(plays,1);
writes=0;
for(let i=0;i<120;i++)syncSounds();
assert.equal(writes,0,'stable frames must not rewrite media volume or mute');
assert.equal(plays,1);
previewMuted=true;items[0].volume=.4;syncSounds();
assert.equal(song.muted,true);assert.equal(song.volume,.4);
song.muted=false;syncSounds();assert.equal(song.muted,true,'external changes are corrected');
// A fade and seek still update the running player.
items[0].fadeIn=4;preview.elapsed=1;syncSounds();
assert.equal(song.volume,.1);
song.currentTime=99;syncSounds();assert.equal(song.currentTime,4);
pauses=0;stopSounds();for(let i=0;i<120;i++)stopSounds();
assert.equal(pauses,1,'already-paused players do not need another pause');
items.push({id:'sfx',file:'effect',kind:'sfx',start:0,dur:10,in:0,volume:1});
preview.elapsed=2;syncSounds();const sfx=soundPlayers.get('sfx');
assert.equal(song.paused,false);assert.equal(sfx.paused,false);
// Songs bridge a clip switch; sound effects stop after the short grace period.
video.paused=true;preview.live=false;clock=1800;syncSounds();
assert.equal(song.paused,false);assert.equal(sfx.paused,true);
clock=4000;syncSounds();assert.equal(song.paused,true);
video.paused=false;preview.live=true;syncSounds();assert.equal(song.paused,false);
preview.elapsed=10;syncSounds();assert.equal(song.paused,true);assert.equal(sfx.paused,true);
items=[];syncSounds();assert.equal(soundPlayers.size,0);
// A sound more than three seconds away is not loaded prematurely.
items=[{id:'later',file:'later',start:30,dur:10,in:0,volume:1}];
preview.elapsed=20;syncSounds();assert.equal(soundPlayers.size,0);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
