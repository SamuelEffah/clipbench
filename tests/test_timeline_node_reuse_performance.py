import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class TimelineNodeReuseTests(unittest.TestCase):
    def test_single_clip_edit_reuses_other_clip_and_sound_nodes(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/short.js').read_text()
        clip = 'function clipBlock(' + source.split('function clipBlock(', 1)[1].split('// A seam', 1)[0]
        sound = 'function soundBlock(' + source.split('function soundBlock(', 1)[1].split('// The top-lane', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let created=0,wavePaints=0,frames=[];
const element=()=>({style:{},dataset:{},clientWidth:100,clientHeight:44,classList:{toggle(){},add(){},remove(){}},
 append(){},setAttribute(){},querySelector:()=>element(),addEventListener(){}});
const document={createElement(){created++;return element();},createElementNS(){created++;return element();}};
const window={devicePixelRatio:1};
const sources={a:{id:'a',name:'Source.mp4'}},byPath=src=>sources[src];
const state={project:{clips:Array.from({length:200},(_,i)=>({src:'a',in:i,out:i+1,note:'clip '+i}))},sel:-1};
const picked=new Set(),voiceWorking=new Set(),clipPeaks=new Map();
const laneOf=()=> 'top',laneLocked=()=>false,laneCount=()=>1;
const outLen=c=>c.out-c.in,clipName=()=> 'Source',esc=String,voiceKey=c=>c.in;
const volumeOf=c=>c.volume??1,MAX_VOLUME=2,SND_NS='svg';
const requestAnimationFrame=fn=>frames.push(fn),drawClipWave=()=>wavePaints++;
const paintWhenVisible=(el,paint)=>paint();
let selected=-1;const pickClip=i=>selected=i;
''' + clip + sound + r'''
function render(){
 for(const block of [clipBlock,soundBlock]){block.previous=block.cache;block.cache=new WeakMap();}
 const result=state.project.clips.map((c,i)=>[clipBlock(c,i,i*100,100,false),soundBlock(c,i,i,100,sources.a)]);
 clipBlock.previous=soundBlock.previous=null;
 const pending=frames;frames=[];pending.forEach(fn=>fn());return result;
}
const before=render();assert.equal(wavePaints,200);
created=0;wavePaints=0;
state.project={...state.project,clips:state.project.clips.map((c,i)=>i===100?{...c,note:'edited'}:c)};
const after=render();
for(let i=0;i<200;i++)for(let kind=0;kind<2;kind++)assert.equal(before[i][kind]===after[i][kind],i!==100);
assert.ok(created<20,`single clip edit created ${created} nodes`);
assert.equal(wavePaints,1,'only the changed clip waveform should be painted');
created=0;wavePaints=0;const stable=render();assert.equal(created,0);assert.equal(wavePaints,0);
state.sel=5;const selection=render();assert.notEqual(stable[5][0],selection[5][0]);assert.equal(stable[6][0],selection[6][0]);
picked.add(6);const multiple=render();assert.ok(multiple[6][0].className.includes('multi'));
// Moving a clip must refresh handlers that capture its global index.
const old=state.project.clips[0];state.project.clips=[state.project.clips[1],old,...state.project.clips.slice(2)];
const reordered=render();reordered[1][1].onclick();assert.equal(selected,1);
const count=wavePaints;window.devicePixelRatio=2;render();assert.equal(wavePaints,count+200);
voiceWorking.add(state.project.clips[0].in);const processing=render();assert.notEqual(processing[0][1],reordered[0][1]);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
