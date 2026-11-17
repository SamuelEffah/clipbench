import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class MissingSourceReload(unittest.TestCase):
    def test_removed_source_stays_removed_after_save_and_project_reload(self):
        app = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        orientation = 'const canon =' + app.split('const canon =', 1)[1].split('// B-roll', 1)[0]
        summary = 'function sourceRowsSummary(' + app.split('function sourceRowsSummary(', 1)[1].split('const sourceDisplayName', 1)[0]
        load = 'async function loadProject(' + app.split('async function loadProject(', 1)[1].split('// While streaming', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
const clip={src:'/missing/original.mp4',in:2,out:8,caption:'Keep my edit'};
const state={mode:'clip',project:{name:'demo',clips:[clip],other:[]},library:[]};
let saved,sessionReady=false;
const referencedThumbs=x=>x;
const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,{});return nodes.get(id);};
const changed=()=>{saved=JSON.parse(JSON.stringify(canon()));};
const toast=()=>{},api=async()=>saved,saveEditorSession=()=>{},flushSave=async()=>{};
const localStorage={setItem(){}},preview={on:false},video={pause(){}},document={activeElement:null};
const closePreview=()=>{},resetHistory=()=>{},dropVideo=()=>{},loadAssets=async()=>{},rememberProject=()=>{},loadChannel=async()=>{},restoreEditorSession=async()=>{},render=()=>{};
''' + orientation + summary + load + r'''
(async()=>{
 assert.equal(sourceRowsSummary(state.project,[]).missing.length,1);
 removeMissingSource(clip.src);
 assert.deepEqual(saved.hiddenSources,[clip.src]);
 assert.equal(sourceRowsSummary(state.project,[]).missing.length,0);
 await loadProject('demo');
 assert.equal(sourceRowsSummary(state.project,[]).missing.length,0,'removed source must stay hidden after reload');
 assert.equal(state.project.clips.length,1);assert.equal(state.project.clips[0].caption,'Keep my edit');
})().catch(e=>{console.error(e);process.exit(1);});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
