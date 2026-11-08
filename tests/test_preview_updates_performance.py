import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class PreviewUpdates(unittest.TestCase):
    def test_unchanged_frames_avoid_writes_and_duplicate_caption_measurements(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        def extract(name, end):
            return 'function ' + name + source.split('function ' + name, 1)[1].split(end, 1)[0]
        code = extract('setPlaybackValue(', '\nfunction placePlayhead')
        code += extract('placeCaption(', '// Collect preview timing')
        code += extract('updatePreview()', '\nfunction tick()')
        captions = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/captions.js').read_text()
        code += 'function paintCaption(' + captions.split('function paintCaption(', 1)[1].split('// New text', 1)[0]
        script = r'''
const assert = require('node:assert/strict');
let writes=0, measures=0, lookups=0;
const tracked = target => new Proxy(target, {set(t,k,v){writes++; t[k]=v; return true;}});
const attrs = {href:''};
const icon = {getAttribute:k=>attrs[k], setAttribute(k,v){writes++;attrs[k]=v;}};
const ids = {};
const $ = id => ids[id] ||= tracked({textContent:'',hidden:false,dataset:{},style:tracked({}),
  querySelector:()=>icon, getAttribute:k=>attrs[k], setAttribute(k,v){writes++;attrs[k]=v;}});
let width=100;
Object.defineProperties($('cCap'), Object.fromEntries(['offsetLeft','offsetTop','offsetWidth','offsetHeight'].map(k=>[k,{get(){measures++;return k==='offsetWidth'?width:20;}}])));
const segs = Array.from({length:2}, ()=>({firstChild:{style:tracked({})},classList:{toggle(){}}}));
const document = {querySelectorAll:()=>segs};
const clip = {caption:'Hello',scale:1};
const state = {project:{clips:[clip,{}]}};
const preview = {idx:0,done:false,live:false};
const video = {paused:true};
let capHome = {width:300,bottom:400};
const DEFAULT_LOOK='plain', DEFAULT_HIGHLIGHT='yellow';
const canvasOf=()=>[640,480], captionSize=()=>40, applyCaptionSize=()=>{};
const capStyleOf=c=>{lookups++;return {at:null,scale:c?.scale||1,rot:0,look:'plain',hi:'yellow'};};
const inShort=()=>true, previewTiming=()=>({lens:[5,5],total:10,start:preview.idx*5,tops:2,place:preview.idx+1});
let position=2;
const clipPos=()=>position, stampShort=String;
const paintLiveCap=()=>{};
const captionAt=c=>c?.caption ? {key:c.caption,words:[c.caption],lit:-1} : null;
''' + code + r'''
updatePreview();
writes=0; measures=0; lookups=0;
for(let i=0;i<120;i++) updatePreview();
assert.equal(measures,480,'one caption box measurement per frame');
assert.equal(lookups,0,'stable frames reuse the resolved caption style');
assert.equal(writes,0,'unchanged preview frames should not rewrite controls');
preview.live=true; updatePreview();
assert.equal(segs[0].firstChild.style.width,'40%');
assert.equal($('thElapsed').textContent,'2');
position=4; width=140; clip.scale=2; clip.caption='Edited'; state.project.clips=[...state.project.clips]; updatePreview();
assert.equal(segs[0].firstChild.style.width,'80%');
assert.equal($('capSel').style.width,'140px');
assert.equal($('capRead').textContent,'200% · 0°');
assert.equal($('cCap').textContent,'Edited');
preview.idx=1; updatePreview(); assert.equal($('thLabel').textContent,'Clip 2 of 2');
assert.equal($('capSel').hidden,true);
preview.done=true; updatePreview();
assert.equal($('thElapsed').textContent,'10'); assert.equal(icon.getAttribute('href'),'#replay');
assert.equal($('thPlay').getAttribute('aria-label'),'Replay');
// Before caption placement is available, the selection still synchronizes.
capHome=null; $('cCap').textContent=''; $('capSel').hidden=false;
updatePreview(); assert.equal($('capSel').hidden,true);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
