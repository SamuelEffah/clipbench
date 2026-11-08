import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class YouTubeVisibilityPollingTests(unittest.TestCase):
    def test_hidden_polling_pauses_and_return_refreshes_without_duplicate_requests(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/youtube.js').read_text()
        source = source.replace('function ytPaint() {', 'function originalYtPaint() {')
        script = r'''
const assert=require('node:assert/strict');
let publishName='demo',calls=0,paints=0,uploadState='uploading',release=null;
const listeners={},document={hidden:false,addEventListener:(event,fn)=>listeners[event]=fn};
let timerId=0;const timers=new Map(),setTimeout=(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId},clearTimeout=id=>timers.delete(id);
const node={};const $=()=>node,ytPaint=()=>paints++,toast=()=>{};
let api=async path=>{calls++;if(release)await release.promise;return path==='/api/youtube'?{configured:true,connected:true}:{state:uploadState,pct:30};};
''' + source + r'''
(async()=>{
 await ytRefresh();assert.equal(calls,2);assert.equal(timers.size,1);
 document.hidden=true;listeners.visibilitychange();assert.equal(timers.size,0);
 const before=calls;for(let i=0;i<60;i++)await ytRefresh();assert.equal(calls,before,'hidden tab should issue no polling requests');
 document.hidden=false;await listeners.visibilitychange();assert.equal(calls,before+2,'return must refresh immediately');
 await new Promise(setImmediate);assert.equal(timers.size,1);
 let finish;release={promise:new Promise(r=>finish=r)};
 const first=ytRefresh(),second=ytRefresh();assert.equal(calls,before+4,'same-project refreshes share in-flight requests');
 document.hidden=true;listeners.visibilitychange();finish();await Promise.all([first,second]);release=null;
 assert.equal(timers.size,0,'in-flight completion must not restart hidden polling');
 uploadState='done';document.hidden=false;await listeners.visibilitychange();await new Promise(setImmediate);
 assert.equal(yt.upload.state,'done');assert.equal(timers.size,0,'completed uploads stop polling');
 // A late failed response from another project must not overwrite the active status.
 publishName='old';let reject;const original=api;
 const failure=new Promise((resolve,no)=>reject=no);api=()=>failure;const old=ytRefresh();
 api=original;publishName='new';await ytRefresh();const status=yt.status;
 reject(new Error('old request failed'));await old;assert.equal(yt.status,status);assert.equal(yt.name,'new');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
