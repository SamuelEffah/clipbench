import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class MutedPreviewAudioPerformance(unittest.TestCase):
    def test_silent_sounds_do_not_load_or_decode_and_unmuting_resynchronizes(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/audio.js').read_text()
        source = 'const soundPlayers' + source.split('const soundPlayers', 1)[1].split('// ----- Dropping', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let created=0,plays=0,pauses=0,previewMuted=false;
const preview={on:true,done:false,live:true,elapsed:2},video={paused:false},performance={now:()=>1000};
let items=Array.from({length:40},(_,i)=>({id:String(i),file:'sound'+i,kind:'song',start:0,dur:10,in:3,volume:0,...(i%2?{volumeEnd:0}:{})}));
const audioOf=()=>items,setPlaybackValue=(el,key,value)=>{el[key]=value};
class Audio {
 constructor(url){created++;this.paused=true;this.currentTime=0;this.volume=1;this.muted=false;}
 play(){plays++;this.paused=false;return Promise.resolve()}
 pause(){pauses++;this.paused=true;}
}
''' + source + r'''
for(let i=0;i<120;i++)syncSounds();
assert.equal(created,0,'fully muted sounds must not load media');assert.equal(plays,0);
items[0].volume=.7;syncSounds();const player=soundPlayers.get('0');
assert.equal(created,1);assert.equal(plays,1);assert.equal(player.currentTime,5);assert.equal(player.volume,.7);
items[0].volume=0;syncSounds();assert.equal(pauses,1);assert.equal(player.volume,0);
for(let i=0;i<120;i++)syncSounds();assert.equal(pauses,1);assert.equal(created,1);
preview.elapsed=5;items[0].volume=.8;syncSounds();
assert.equal(created,1);assert.equal(plays,2);assert.equal(player.currentTime,8);
items.push({id:'rise',file:'rise',kind:'sfx',start:0,dur:10,in:0,volume:0,volumeEnd:1});
items.push({id:'fall',file:'fall',kind:'sfx',start:0,dur:10,in:0,volume:1,volumeEnd:0});
preview.elapsed=0;syncSounds();assert.equal(created,3,'both directions of audible ramps must still load');
assert.equal(soundPlayers.get('rise').paused,false);assert.equal(soundPlayers.get('rise').volume,0);
previewMuted=true;syncSounds();assert.equal(player.paused,false,'monitor mute retains existing playback behavior');
assert.equal(player.muted,true);
'''
        out = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
