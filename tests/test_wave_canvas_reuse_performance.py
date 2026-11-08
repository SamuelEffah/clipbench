import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class WaveCanvasReusePerformance(unittest.TestCase):
    def test_wave_redraws_reuse_backing_store_and_reset_transform_and_pixels(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        app = (ui / 'app.js').read_text()
        audio = (ui / 'audio.js').read_text()
        short = (ui / 'short.js').read_text()
        helper = ''
        if 'function prepareWaveCanvas(' in app:
            helper = 'function prepareWaveCanvas(' + app.split('function prepareWaveCanvas(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        sound = 'async function drawSoundWave(' + audio.split('async function drawSoundWave(', 1)[1].split('// Drag a block', 1)[0]
        clip = 'async function drawClipWave(' + short.split('async function drawClipWave(', 1)[1].split('\nfunction clipBlock(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
const wave={per_sec:50,peaks:Array(2000).fill(128)},peaksFor=async()=>wave,peaksOfVideo=async()=>wave;
const window={devicePixelRatio:1.25},audioScale={pps:20},volumeOf=c=>c.volume??1,soundGain=c=>c.volume??1;
let writes=0,clears=0,bars=[],sx=1,sy=1,width=0,height=0;
const g={setTransform(a,b,c,d,e,f){assert.deepEqual([a,b,c,d,e,f],[1,0,0,1,0,0]);sx=sy=1;},scale(x,y){sx*=x;sy*=y;},clearRect(...args){assert.equal(sx,1);assert.equal(sy,1);assert.deepEqual(args,[0,0,width,height]);clears++;bars=[];},fillRect(x,y,w,h){bars.push([x*sx,y*sy,w*sx,h*sy]);}};
const canvas={clientWidth:100,clientHeight:28,isConnected:true,getContext:()=>g};
for(const key of ['width','height'])Object.defineProperty(canvas,key,{get(){return key==='width'?width:height;},set(v){writes++;if(key==='width')width=v;else height=v;sx=sy=1;bars=[];}});
const block={querySelector:()=>canvas};
''' + helper + sound + clip + r'''
(async()=>{
for(const kind of ['clip','sound']) {
 width=height=0;canvas.clientWidth=100;window.devicePixelRatio=1.25;
 const item={file:'sound',in:0,out:5,dur:5,start:0,volume:1};
 const draw=()=>kind==='clip'?drawClipWave(canvas,item,{id:'video'}):drawSoundWave(block,item);
 await draw();const expected=bars;assert.equal(width,125);assert.equal(height,35);
 writes=0;clears=0;for(let i=0;i<120;i++)await draw();
 assert.equal(writes,0,`${kind}: stable waveforms must not resize their backing store`);assert.equal(clears,120);assert.deepEqual(bars,expected);
 item.volume=0;await draw();assert.ok(bars.every(bar=>bar[3]===(kind==='clip'?1.5:1)*1.25));
 item.volume=1;item.dur=6;canvas.clientWidth=120;writes=0;await draw();assert.equal(writes,1);assert.equal(width,150);assert.equal(height,35);
 window.devicePixelRatio=2;writes=0;await draw();assert.equal(writes,2);assert.equal(width,240);assert.equal(height,56);
 canvas.isConnected=false;writes=0;const before=clears;await draw();assert.equal(writes,0);assert.equal(clears,before);canvas.isConnected=true;
}
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
