import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class HiddenTimelinePerformance(unittest.TestCase):
    def test_short_mode_skips_source_timeline_and_clip_mode_rebuilds_it(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        timeline = 'function renderTimeline(' + source.split('function renderTimeline(', 1)[1].split('\nconst volumeTop', 1)[0]
        ruler = 'function renderRuler(' + source.split('function renderRuler(', 1)[1].split('// Only a card dragged', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let created=0,waves=0,heads=0,navs=0;
const element=()=>({children:[],style:{},classList:{toggle(){}},append(...els){this.children.push(...els);},appendChild(el){this.children.push(el);},replaceChildren(...els){this.children=els;},setAttribute(){}});
const document={createElement:()=>{created++;return element();}};
const strip=element(),ruler=element(),$=id=>id==='strip'?strip:ruler,waveCanvas=element();
const state={mode:'clip',current:{path:'video',duration:100},project:{clips:Array.from({length:1000},()=>({src:'video',in:0,out:5}))},sel:-1,pendingIn:null};
const view={s:0,e:100},span=()=>100,pos=t=>t,sceneMarks=element;
const scrubClip=()=>{},renderNav=()=>navs++,placeRange=()=>{},outLen=c=>c.out-c.in;
const placePlayhead=()=>heads++,drawWave=()=>waves++;
''' + timeline + ruler + r'''
state.mode='short';renderTimeline();renderRuler();
assert.equal(created,0,'hidden source tracks must not construct DOM');assert.equal(waves,0);assert.equal(heads,0);assert.equal(navs,0);
state.mode='clip';renderTimeline();renderRuler();
assert.equal(strip.children.length,1003);assert.ok(ruler.children.length>0);assert.ok(created>1000);
assert.equal(waves,1);assert.equal(heads,1);assert.equal(navs,1);
const previous=strip.children;state.mode='short';created=0;
state.project.clips=state.project.clips.slice(0,500);
for(let i=0;i<120;i++){renderTimeline();renderRuler();}
assert.equal(created,0);assert.equal(strip.children,previous);assert.equal(waves,1);
state.mode='clip';renderTimeline();renderRuler();assert.equal(strip.children.length,503);assert.notEqual(strip.children,previous);assert.equal(waves,2);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
