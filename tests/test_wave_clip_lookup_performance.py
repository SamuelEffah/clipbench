import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class WaveClipLookupPerformance(unittest.TestCase):
    def test_waveform_preserves_drawing_and_avoids_searching_each_bar(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        helper = 'function waveClipLookup(' + source.split('function waveClipLookup(', 1)[1].split('\nfunction drawWave(', 1)[0]
        draw = 'function drawWave(' + source.split('function drawWave(', 1)[1].split('\nnew ResizeObserver(', 1)[0]
        previous = draw.replace('function drawWave(', 'function previousDraw(').replace('  const clipAt = waveClipLookup(mine);\n', '').replace('const hit = clipAt(tm);', 'const hit = mine.find(({c}) => tm >= c.in && tm < c.out);')
        script = r'''
const assert=require('node:assert/strict');
const state={current:{id:'v',path:'v'},project:{clips:[]},sel:0};
const wave={per_sec:20,peaks:Array.from({length:400},(_,i)=>i%256)},waves={v:wave};
const view={s:0,e:10},span=()=>view.e-view.s,volumeOf=c=>c.volume??1;
const VIDEO_LANE=46,LANE_GAP=4,BAR_W=2,BAR_STEP=3;
const strip={clientWidth:999,clientHeight:100},$=()=>strip;
const window={devicePixelRatio:2},document={documentElement:{}},getComputedStyle=()=>({getPropertyValue:()=> '#f00'});
let rects=[];const ctx={setTransform(){},clearRect(){},fillRect(...args){rects.push([this.fillStyle,...args]);}};
const waveCanvas={width:0,height:0,style:{},getContext:()=>ctx};
''' + helper + draw + previous + r'''
let reads=0;
state.project.clips=Array.from({length:2000},()=>({src:'v',get in(){reads++;return 100;},out:110}));
drawWave();assert.ok(reads<20000,`${reads} clip range reads for 333 waveform bars`);
const optimized=rects;rects=[];reads=0;previousDraw();
assert.ok(reads>600000);assert.deepEqual(rects,optimized);
// Differential rendering covers unsorted and overlapping ranges, first-match priority,
// muted and boosted clips, selection washes, different sources, and timeline zoom.
let seed=63;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let run=0;run<500;run++) {
 state.project.clips=Array.from({length:Math.floor(rand()*50)},()=>{
  const start=rand()*20;return {src:rand()<.2?'other':'v',in:start,out:start+rand()*10,volume:[0,.4,1,2][Math.floor(rand()*4)]};
 });
 state.sel=Math.floor(rand()*state.project.clips.length);view.s=rand()*5;view.e=view.s+rand()*15+.1;
 rects=[];drawWave();const result=rects;rects=[];previousDraw();assert.deepEqual(result,rects);
}
// Strict boundaries and ties keep the earliest clip in the list, even when starts differ.
const clips=[{c:{in:2,out:4},i:0},{c:{in:0,out:5},i:1},{c:{in:2,out:3},i:2},{c:{in:7,out:7},i:3}];
const lookup=waveClipLookup(clips);
for(const t of [-1,0,1,2,3,4,5,7])assert.equal(lookup(t),clips.find(({c})=>t>=c.in&&t<c.out));
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
