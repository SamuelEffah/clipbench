import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class AutosaveSerializationTests(unittest.TestCase):
    def test_slow_saves_coalesce_and_flush_waits_for_latest_edit(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        save = 'async function save()' + source.split('async function save()', 1)[1].split('// Save the open project', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
const state={project:{name:'demo',value:0}};
let editCount=0,unsaved=true,retryWait=2000,committed=state.project,projectNames=['demo'];
const $=()=>({classList:{remove(){},add(){}}}),toast=()=>{},rememberThumbnails=()=>null,referencedThumbs=p=>p;
const canon=()=>({...state.project});
const bodies=[],releases=[];let active=0,maximum=0;
const api=async(path,method,body)=>{bodies.push(body);maximum=Math.max(maximum,++active);await new Promise(r=>releases.push(r));active--;return {};};
''' + save + r'''
(async()=>{
 const first=save();const waiting=[];
 for(let i=1;i<=50;i++){state.project={name:'demo',value:i};editCount++;waiting.push(save());}
 assert.equal(bodies.length,1);assert.equal(unsaved,true);
 releases.shift()();await new Promise(setImmediate);
 assert.equal(bodies.length,2);assert.equal(bodies[1].value,50);
 assert.equal(unsaved,true,'first response cannot mark newer edits saved');
 releases.shift()();await Promise.all([first,...waiting]);
 assert.equal(maximum,1);assert.equal(unsaved,false);
 await Promise.resolve();const next=save();assert.equal(bodies.length,3);releases.shift()();await next;
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
