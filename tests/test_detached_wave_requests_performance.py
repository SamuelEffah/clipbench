import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class DetachedWaveRequestsPerformance(unittest.TestCase):
    def test_detached_blocks_skip_wave_requests_and_late_removal_skips_drawing(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        audio = (ui / 'audio.js').read_text()
        short = (ui / 'short.js').read_text()
        sound = 'async function drawSoundWave(' + audio.split('async function drawSoundWave(', 1)[1].split('// Drag a block', 1)[0]
        clip = 'async function drawClipWave(' + short.split('async function drawClipWave(', 1)[1].split('\nfunction clipBlock(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let requests=0,prepared=0,bars=0,resolve;
const wave={per_sec:50,peaks:Array(100).fill(128)};
let respond=async()=>wave;
const peaksFor=async id=>{requests++;return respond(id);},peaksOfVideo=async v=>{requests++;return respond(v.id);};
const prepareWaveCanvas=()=>{prepared++;return {fillRect(){bars++;}};};
const audioScale={pps:20},window={devicePixelRatio:1},volumeOf=c=>c.volume??1,soundGain=c=>c.volume??1;
const item={file:'sound',in:0,out:1,start:0,dur:1,volume:1},video={id:'video'};
const makeCanvas=()=>({isConnected:false,clientWidth:20,clientHeight:28});
''' + sound + clip + r'''
(async()=>{
const stale=Array.from({length:200},()=>makeCanvas());
await Promise.all(stale.flatMap((canvas,i)=>[drawClipWave(canvas,item,{id:`video${i}`}),drawSoundWave({querySelector:()=>canvas},{...item,file:`sound${i}`})]));
assert.equal(requests,0,'discarded timeline blocks must not start waveform work');assert.equal(prepared,0);assert.equal(bars,0);
await drawSoundWave({querySelector:()=>null},item);assert.equal(requests,0,'a missing waveform canvas needs no request');
for(const kind of ['clip','sound']) {
 const canvas=makeCanvas();canvas.isConnected=true;
 const draw=()=>kind==='clip'?drawClipWave(canvas,item,video):drawSoundWave({querySelector:()=>canvas},item);
 respond=()=>new Promise(r=>resolve=r);requests=prepared=bars=0;
 const pending=draw();assert.equal(requests,1);canvas.isConnected=false;resolve(wave);await pending;assert.equal(prepared,0);assert.equal(bars,0);
 canvas.isConnected=true;respond=async()=>wave;await draw();assert.equal(requests,2);assert.equal(prepared,1);assert.ok(bars>0);
 respond=async()=>({per_sec:50,peaks:[]});prepared=bars=0;await draw();assert.equal(prepared,0);assert.equal(bars,0);
}
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
