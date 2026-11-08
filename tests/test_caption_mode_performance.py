import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class CaptionModePerformance(unittest.TestCase):
    def test_bulk_membership_avoids_repeated_array_searches(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/textpanel.js').read_text()
        helper = 'function captionModeTargets(' + source.split('function captionModeTargets(', 1)[1].split('async function applyCaptionMode(', 1)[0]
        short = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/short.js').read_text()
        runs = 'function captionRuns(' + short.split('function captionRuns(', 1)[1].split('\nfunction textRow(', 1)[0]
        mode = 'async function applyCaptionMode(' + source.split('async function applyCaptionMode(', 1)[1].split('\nfunction applyWordColour(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let scans=0,boxReads=0,all=true,newCaptionMode='word',selected,changes=[],listened=[];
const state={project:{clips:[]}};
const textClip=()=>selected,isTop=c=>!c.lane||c.lane==='top',isSynced=c=>Boolean(c.synced),captionOf=c=>c.caption||'';
const $=id=>{boxReads++;return {checked:all};};
const changed=(...args)=>changes.push(args),autoCaption=async n=>listened.push(n);
const includes=Array.prototype.includes;
Array.prototype.includes=function(...args){scans+=this.length;return includes.apply(this,args);};
''' + runs + helper + mode + r'''
(async()=>{
state.project.clips=Array.from({length:2000},()=>({caption:'hello'}));selected=state.project.clips[0];
await applyCaptionMode('text');
assert.equal(scans,0,'bulk mode changes must not search a target array for each clip');
assert.ok(boxReads<=1,'read the all-clips checkbox once');
assert.ok(state.project.clips.every(c=>c.capMode==='text'));assert.equal(newCaptionMode,'text');
assert.deepEqual(changes,[[false,'capmode:text']]);assert.deepEqual(listened,[]);
// Only eligible top-lane captions change; untimed captions are queued in timeline order.
const clips=[{caption:'a',words:[[1]]},{caption:'b'},{caption:'lower',lane:'lower',words:[[1]]},{caption:'',capStop:true},{caption:'c'}];
state.project.clips=clips;selected=clips[1];changes=[];listened=[];
await applyCaptionMode('phrase');
assert.deepEqual(listened,[1,4]);assert.equal(state.project.clips[0].capMode,'phrase');
for(const i of [1,2,3,4])assert.equal(state.project.clips[i],clips[i]);
all=false;selected=state.project.clips[1];changes=[];listened=[];
await applyCaptionMode('word');assert.deepEqual(listened,[1]);assert.deepEqual(changes,[]);
selected=state.project.clips[0];await applyCaptionMode('word');
assert.equal(state.project.clips[0].capMode,'word');assert.deepEqual(changes,[[false,'capmode:word']]);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
