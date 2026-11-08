import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class ThumbnailSavePayloadTests(unittest.TestCase):
    def test_following_saves_use_references_and_keep_undo_and_concurrent_edits(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        def function(name):
            return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        helpers = ''.join(function(name) for name in ('referencedThumbs', 'rememberThumbnails')) if 'function referencedThumbs(' in source else ''
        canon = 'const canon =' + source.split('const canon =', 1)[1].split('const orient', 1)[0]
        favorites = 'async function saveFavorites(' + source.split('async function saveFavorites(', 1)[1].split('\nfunction toggleFavorite(', 1)[0]
        save = 'async function save()' + source.split('async function save()', 1)[1].split('// Save the open project', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
const uri='data:image/jpeg;base64,'+'x'.repeat(12000),url='/clip-thumb/'+'a'.repeat(64)+'.jpg';
const original={name:'demo',clips:Array.from({length:100},()=>({src:'source',thumb:uri,caption:'Original'})),other:[]};
const state={project:original,mode:'short',favorites:[]};let committed=original,editCount=0,retryWait=2000,unsaved=true,projectNames=['demo'];
const $=()=>({classList:{remove(){},add(){}}}),toast=()=>{},clearTimeout=()=>{},setTimeout=()=>{};
const renderFavs=()=>{},renderTray=()=>{},projectQuery=()=>'?project=demo';
const bodies=[];let hold=false,finish;
const api=async(path,method,body)=>{
 bodies.push(body);
 const items=Array.isArray(body)?body:body.clips;
 const response={ok:true,thumbs:items.flatMap((c,i)=>c.thumb===uri?[{path:Array.isArray(body)?[i,'thumb']:['clips',i,'thumb'],url}]:[])};
 if(hold)return new Promise(r=>finish=()=>r(response));
 return response;
};
''' + helpers + canon + save + favorites + r'''
(async()=>{
 await save();assert.equal(state.project.clips[0].thumb,url,'successful save should replace current embedded images');
 assert.equal(original.clips[0].thumb,uri,'undo snapshots must remain unchanged');
 assert.equal(committed,state.project);
 await save();assert.ok(JSON.stringify(bodies[1]).length<JSON.stringify(bodies[0]).length/20,'later autosaves should contain references');
 state.project=original;await save();assert.equal(bodies[2].clips[0].thumb,url,'undo should reuse known references');
 await saveFavorites([{src:'source',thumb:uri}]);assert.equal(state.favorites[0].thumb,url);
 hold=true;state.project={...original,clips:[...original.clips]};const pending=save();
 const other='data:image/jpeg;base64,new-image';
 state.project={...state.project,clips:state.project.clips.map((c,i)=>i===0?{...c,caption:'Edited',thumb:other}:c)};editCount++;committed=state.project;
 finish();await pending;assert.equal(state.project.clips[0].caption,'Edited');assert.equal(state.project.clips[0].thumb,other);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
