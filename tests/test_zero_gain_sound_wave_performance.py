import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class ZeroGainSoundWavePerformance(unittest.TestCase):
    def test_zero_gain_bars_skip_peak_scans_and_volume_ramps_keep_shape(self):
        audio = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/audio.js').read_text()
        draw = 'async function drawSoundWave(' + audio.split('async function drawSoundWave(', 1)[1].split('// Drag a block', 1)[0]
        gain = 'function soundGain(' + audio.split('function soundGain(', 1)[1].split('\nfunction stopSounds(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let reads=0,bars=[];const raw=Array.from({length:180000},(_,i)=>i%256);
const wave={per_sec:50,peaks:new Proxy(raw,{get(a,k){if(/^\d+$/.test(String(k)))reads++;return a[k];}})},peaksFor=async()=>wave;
const endLevel=a=>(a.volumeEnd===undefined||a.volumeEnd===null?a.volume:a.volumeEnd);
const window={devicePixelRatio:1},audioScale={pps:1/12},prepareWaveCanvas=()=>({set fillStyle(v){},fillRect(...a){bars.push(a);}});
const canvas={isConnected:true,clientHeight:28},block={querySelector:()=>canvas};
''' + gain + draw + r'''
(async()=>{
const a={file:'song',in:0,dur:3600,start:3,volume:0,fadeIn:10,fadeOut:20};
await drawSoundWave(block,a);
assert.deepEqual(bars,Array.from({length:150},(_,i)=>[i*2,13.5,1.4,1]));
assert.equal(reads,0,`${reads} peak reads for zero gain`);
for(const levels of [[0,1],[1,0],[.7,null],[.4,1.5]]){
 [a.volume,a.volumeEnd]=levels;bars=[];reads=0;await drawSoundWave(block,a);
 assert.ok(reads>0);
 for(let i=0;i<bars.length;i++){
  const x=i*2,t0=a.in+x/audioScale.pps,t1=a.in+Math.min(300,x+2)/audioScale.pps;
  const from=Math.floor(t0*50),to=Math.max(from+1,Math.ceil(t1*50));
  let peak=0;for(let n=from;n<to&&n<raw.length;n++)peak=Math.max(peak,raw[n]);
  const amp=Math.min(1,peak/255*soundGain(a,a.start+x/audioScale.pps,true));
  const height=Math.max(1,amp*26);
  assert.deepEqual(bars[i],[x,14-height/2,1.4,height]);
 }
}
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
