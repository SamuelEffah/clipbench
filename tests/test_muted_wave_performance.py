import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class MutedWavePerformance(unittest.TestCase):
    def test_muted_clip_draws_identical_bars_without_scanning_peaks(self):
        short = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/short.js').read_text()
        draw = 'async function drawClipWave(' + short.split('async function drawClipWave(', 1)[1].split('\nfunction clipBlock(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let reads=0,bars=[];
const raw=Array.from({length:180000},(_,i)=>i%256);
const wave={per_sec:50,peaks:new Proxy(raw,{get(a,k){if(/^\d+$/.test(String(k)))reads++;return a[k];}})};
const peaksOfVideo=async()=>wave,volumeOf=c=>c.volume;
const window={devicePixelRatio:1},prepareWaveCanvas=()=>({set fillStyle(v){},fillRect(...args){bars.push(args);}});
const canvas={isConnected:true,clientWidth:300,clientHeight:28};
''' + draw + r'''
(async()=>{
const c={in:0,out:3600,volume:0,fadeIn:2,fadeOut:3};
await drawClipWave(canvas,c,{});
assert.deepEqual(bars,Array.from({length:100},(_,i)=>[i*3,14-.75,2,1.5]));
assert.equal(reads,0,`${reads} peak reads for a muted clip`);
c.volume=.7;bars=[];await drawClipWave(canvas,c,{});
assert.ok(reads>=180000);assert.ok(bars.some(b=>b[3]>1.5));
for(let i=0;i<bars.length;i++){
 const x=i*3,t0=c.in+x/300*(c.out-c.in),t1=c.in+Math.min(300,x+3)/300*(c.out-c.in);
 const from=Math.floor(t0*50),to=Math.max(from+1,Math.ceil(t1*50));
 let peak=0;for(let n=from;n<to&&n<raw.length;n++)peak=Math.max(peak,raw[n]);
 const pos=x/300*(c.out-c.in),len=c.out-c.in;
 const height=Math.max(1.5,peak/255*.7*Math.min(1,pos/2)*Math.min(1,(len-pos)/3)*26);
 assert.deepEqual(bars[i],[x,14-height/2,2,height]);
}
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
