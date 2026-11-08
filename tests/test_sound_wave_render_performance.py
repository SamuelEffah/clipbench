import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class SoundWaveRenderPerformance(unittest.TestCase):
    def test_waveform_does_not_copy_sound_metadata_per_bar_and_keeps_amplitudes(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/audio.js').read_text()
        draw = 'async function drawSoundWave(' + source.split('async function drawSoundWave(', 1)[1].split('// Drag a block', 1)[0]
        gain = 'const endLevel' + source.split('const endLevel', 1)[1].split('\nfunction stopSounds()', 1)[0]
        app = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        helper = 'function prepareWaveCanvas(' + app.split('function prepareWaveCanvas(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
const wave={per_sec:50,peaks:Array.from({length:2000},(_,i)=>i%256)};
const peaksFor=async()=>wave;
const audioScale={pps:40},window={devicePixelRatio:2};
let bars=[],scales=[],metadataReads=0;
const canvas={isConnected:true,clientHeight:28,getContext(){return {setTransform(){},clearRect(){},scale(...v){scales.push(v);},fillRect(...v){bars.push(v);}};}};
const block={querySelector:()=>canvas};
''' + helper + gain + draw + r'''
(async()=>{
for(const patch of [{},{volume:0},{volume:2,volumeEnd:.3,fadeIn:2,fadeOut:1},{in:3.7,dur:2.3,start:10.1,volumeEnd:0}]) {
 const a={file:'sound',in:1,dur:10,start:2,volume:1,...patch,
 get label(){metadataReads++;return 'A sound with metadata';}};
 bars=[];scales=[];metadataReads=0;
 await drawSoundWave(block,a);
 assert.equal(metadataReads,0,'waveform bars should not copy unrelated sound metadata');
 assert.deepEqual(scales,[[2,2]]);
 const w=Math.max(1,Math.round(a.dur*40)),h=28;
 assert.equal(canvas.width,w*2);assert.equal(canvas.height,h*2);
 const expected=[];
 for(let x=0;x<w;x+=2) {
  const t0=a.in+x/40,t1=a.in+Math.min(w,x+2)/40;
  const from=Math.floor(t0*50),to=Math.max(from+1,Math.ceil(t1*50));
  let peak=0;for(let i=from;i<to&&i<wave.peaks.length;i++)peak=Math.max(peak,wave.peaks[i]);
  const amp=Math.min(1,peak/255*soundGain(a,a.start+x/40,true));
  const bar=Math.max(1,amp*(h-2));expected.push([x,h/2-bar/2,1.4,bar]);
 }
 assert.deepEqual(bars,expected);
}
canvas.isConnected=false;bars=[];
await drawSoundWave(block,{file:'sound'});assert.deepEqual(bars,[]);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
