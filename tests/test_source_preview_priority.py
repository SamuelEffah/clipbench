"""Source preparation takes precedence over optional analysis."""
import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class SourcePreviewPriorityTests(unittest.TestCase):
    def test_analysis_waits_for_playable_source_and_ignores_stale_selection(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        code = 'async function openVideo(' + source.split('async function openVideo(', 1)[1].split('\nfunction updateTime()', 1)[0]
        script = r'''
const assert = require('node:assert/strict');
const calls=[];
let loadToken=0;
const state={};
const video={pause(){},dataset:{},set src(value){this.url=value;}};
const streaming=()=>false, fitView=()=>{},labelSource=()=>{},render=()=>{};
const showOverlay=()=>{},hideOverlay=()=>{},updateTime=()=>{};
const loadWave=v=>calls.push('wave:'+v.id),loadScenes=v=>calls.push('scenes:'+v.id);
let ready;
const api=()=>new Promise(r=>ready=r);
''' + code + r'''
(async()=>{
 const first=openVideo({id:'a',ready:false});
 assert.deepEqual(calls,[],'analysis must not compete with preview preparation');
 ready({state:'ready'});
 await Promise.resolve();await Promise.resolve();
 assert.equal(video.url,'/media/a');
 assert.deepEqual(calls,[],'wait until media metadata is available');
 video.onloadedmetadata();
 assert.equal(await first,true);
 assert.deepEqual(calls,['wave:a','scenes:a']);
 calls.length=0;
 const stale=openVideo({id:'b',ready:false});
 const finishStale=ready;
 const current=openVideo({id:'c',ready:true});
 video.onloadedmetadata();
 assert.equal(await current,true);
 finishStale({state:'ready'});
 assert.equal(await stale,false);
 assert.deepEqual(calls,['wave:c','scenes:c']);
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ready_preview_does_not_wait_for_a_polling_timer(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        code = 'async function openVideo(' + source.split('async function openVideo(', 1)[1].split('\nfunction updateTime()', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let loadToken=0;
const state={}, calls=[];
const video={pause(){},dataset:{},set src(value){queueMicrotask(()=>this.onloadedmetadata());}};
const streaming=()=>false,fitView=()=>{},labelSource=()=>{},render=()=>{};
const showOverlay=()=>{},hideOverlay=()=>{},updateTime=()=>{},loadWave=()=>{},loadScenes=()=>{};
const setTimeout=()=>{throw Error('unnecessary polling timer');};
const api=async(path,method)=>{calls.push([path,method]);return {state:method==='POST'?'working':'ready',pct:0};};
''' + code + r'''
(async()=>{
 assert.equal(await openVideo({id:'a',ready:false}),true);
 assert.deepEqual(calls,[['/api/proxy/a','POST'],['/api/proxy/a?wait=1',undefined]]);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
