import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class HiddenPreviewSegmentsPerformance(unittest.TestCase):
    def test_short_mode_skips_hidden_segment_creation_and_frame_updates(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        def function(name):
            return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
let created=0,queries=0,segmentWrites=0,toggles=0,started=-1;
const segs={children:[],set innerHTML(v){this.children=[];},appendChild(el){this.children.push(el);}};
const attrs={},icon={getAttribute:k=>attrs[k],setAttribute(k,v){attrs[k]=v;}};
const ids=new Map(),$=id=>{if(id==='segs')return segs;if(!ids.has(id))ids.set(id,{textContent:'',querySelector:()=>icon,getAttribute:k=>attrs[k],setAttribute(k,v){attrs[k]=v;}});return ids.get(id);};
const document={createElement:()=>{created++;return {style:{},attrs:{},firstChild:{style:new Proxy({},{set(t,k,v){segmentWrites++;t[k]=v;return true;}})},classList:{toggle(){toggles++;}},setAttribute(k,v){this.attrs[k]=v;}};},querySelectorAll:()=>{queries++;return segs.children;}};
const state={mode:'short',project:{clips:Array.from({length:2000},()=>({}))}},preview={idx:1000,live:true,done:false},video={paused:false};
const isTop=()=>true,outLen=()=>5,startPreviewAt=i=>started=i;
const previewTiming=()=>({lens:state.project.clips.map(()=>5),total:state.project.clips.length*5,start:preview.idx*5,tops:state.project.clips.length,place:preview.idx+1});
const clipPos=()=>2,stampShort=String,captionAt=()=>null,paintCaption=()=>{},paintLiveCap=()=>{},placeCaption=()=>{},syncCapSel=()=>{},capHome={};
const setPlaybackValue=(target,key,value)=>{if(target[key]!==value)target[key]=value;};
''' + function('buildSegs') + function('updatePreview') + r'''
buildSegs();assert.equal(created,0,'Short mode must not build hidden legacy segment buttons');
for(let i=0;i<120;i++)updatePreview();assert.equal(queries,0);assert.equal(segmentWrites,0);assert.equal(toggles,0);assert.equal(preview.elapsed,5002);assert.equal($('thElapsed').textContent,'5002');
// Legacy Clip preview still builds the full strip with correct jump targets and progress.
state.mode='clip';buildSegs();assert.equal(segs.children.length,2000);assert.equal(created,2000);
segs.children[1999].onclick();assert.equal(started,1999);assert.equal(segs.children[1999].attrs['aria-label'],'Go to clip 2000');
updatePreview();assert.equal(queries,1);assert.equal(segs.children[999].firstChild.style.width,'100%');assert.equal(segs.children[1000].firstChild.style.width,'40%');assert.equal(segs.children[1001].firstChild.style.width,'0%');
const before=segs.children;state.mode='short';created=queries=segmentWrites=toggles=0;state.project.clips=state.project.clips.slice(0,500);preview.idx=0;
buildSegs();updatePreview();assert.equal(segs.children,before);assert.equal(created,0);assert.equal(queries,0);assert.equal(segmentWrites,0);assert.equal(toggles,0);
state.mode='clip';buildSegs();assert.equal(segs.children.length,500);assert.notEqual(segs.children,before);
preview.done=true;updatePreview();assert.ok(segs.children.every(el=>el.firstChild.style.width==='100%'));assert.equal($('thElapsed').textContent,'2500');
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
