import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class MutedSourceWavePerformance(unittest.TestCase):
    def test_muted_ranges_skip_peaks_and_keep_warning_bars(self):
        app = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        helper = 'function waveClipLookup(' + app.split('function waveClipLookup(', 1)[1].split('\nfunction drawWave(', 1)[0]
        draw = 'function drawWave(' + app.split('function drawWave(', 1)[1].split('\nnew ResizeObserver(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');let reads=0,rects=[];
const raw=Array.from({length:180000},(_,i)=>i%256);
const wave={per_sec:50,peaks:new Proxy(raw,{get(a,k){if(/^\d+$/.test(String(k)))reads++;return a[k];}})},waves={v:wave};
const clip={src:'v',in:0,out:3600,volume:0},state={current:{id:'v',path:'v'},project:{clips:[clip]},sel:0};
const view={s:0,e:3600},span=()=>view.e-view.s,volumeOf=c=>c.volume;
const VIDEO_LANE=46,LANE_GAP=4,BAR_W=2,BAR_STEP=3;
const strip={clientWidth:300,clientHeight:100},$=()=>strip,window={devicePixelRatio:1};
const document={documentElement:{}},getComputedStyle=()=>({getPropertyValue:()=>'#f00'});
const ctx={setTransform(){},clearRect(){},fillRect(...a){rects.push([this.fillStyle,...a]);}};
const waveCanvas={width:0,height:0,style:{},getContext:()=>ctx};
''' + helper + draw + r'''
drawWave();assert.equal(reads,0,`${reads} peak reads for a muted source range`);
assert.equal(rects.length,201);assert.deepEqual(rects[0],['rgba(111,155,255,.22)',0,0,300,50]);
for(let i=0;i<100;i++){
 assert.deepEqual(rects[1+i*2],['rgba(232,224,210,.2)',i*3,24.25,2,1.5]);
 assert.deepEqual(rects[2+i*2],['#f00',i*3,24.25,3,1.5]);
}
clip.out=1800;reads=0;rects=[];drawWave();assert.ok(reads>0);assert.ok(reads<180000);
assert.equal(rects.filter(r=>r[0]==='#f00').length,50);
clip.volume=1;reads=0;rects=[];drawWave();assert.ok(reads>=180000);assert.equal(rects.filter(r=>r[0]==='#f00').length,0);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
