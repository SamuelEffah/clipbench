import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class PreviewPositionPerformance(unittest.TestCase):
    def test_preview_reuses_one_clip_position_for_time_progress_and_caption(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        update = 'function updatePreview(' + source.split('function updatePreview(', 1)[1].split('\nfunction tick(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let calls=0,position=2.5,captionPosition=null,painted;
const clip={},state={project:{clips:[clip,{}]}},preview={idx:0,live:true,done:false},video={paused:false};
const previewTiming=()=>({lens:[5,5],total:10,start:preview.idx*5,tops:2,place:preview.idx+1});
const clipPos=c=>{assert.equal(c,clip);calls++;return position;},stampShort=String;
const captionAt=(c,pos,live)=>{captionPosition=pos;return {c,pos,live};},paintCaption=(el,cap)=>painted=cap,paintLiveCap=()=>{};
const capHome={},placeCaption=()=>{},syncCapSel=()=>{},setPlaybackValue=(target,key,value)=>target[key]=value;
const attrs={},icon={getAttribute:k=>attrs[k],setAttribute(k,v){attrs[k]=v;}};
const ids=new Map(),$=id=>{if(!ids.has(id))ids.set(id,{textContent:'',querySelector:()=>icon,getAttribute:k=>attrs[k],setAttribute(k,v){attrs[k]=v;}});return ids.get(id);};
const segs=Array.from({length:2},()=>({firstChild:{style:{}},classList:{toggle(){}}})),document={querySelectorAll:()=>segs};
''' + update + r'''
updatePreview();assert.equal(calls,1,'a live preview should calculate clip position only once');assert.equal(preview.elapsed,2.5);assert.equal(segs[0].firstChild.style.width,'50%');assert.equal(captionPosition,2.5);assert.equal(painted.live,true);
position=6;calls=0;updatePreview();assert.equal(calls,1);assert.equal(preview.elapsed,5);assert.equal(segs[0].firstChild.style.width,'100%');assert.equal(captionPosition,6);
preview.live=false;video.paused=true;calls=0;updatePreview();assert.equal(calls,1);assert.equal(preview.elapsed,0);assert.equal(segs[0].firstChild.style.width,'0%');assert.equal(painted.live,false);
preview.done=true;calls=0;updatePreview();assert.equal(calls,0);assert.equal(preview.elapsed,10);assert.equal(painted,null);assert.equal(attrs.href,'#replay');
preview.done=false;preview.idx=10;calls=0;updatePreview();assert.equal(calls,0);assert.equal(preview.elapsed,0);assert.equal(captionPosition,0);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
