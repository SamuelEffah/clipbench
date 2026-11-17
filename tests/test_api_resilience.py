import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class ApiResilience(unittest.TestCase):
    def test_concurrent_reads_share_work_without_caching_results_or_mutations(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        api = 'async function api(' + source.split('async function api(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
const state={profileId:'one',project:{name:'demo'}};
const location={search:''};
let calls=0,releases=[];
const fetch=async()=>{calls++;return await new Promise(resolve=>releases.push(()=>resolve({ok:true,json:async()=>({ok:true})})));};
'''+api+r'''
(async()=>{
 const reads=Array.from({length:50},()=>api('/api/projects'));
 assert.equal(calls,1);
 state.profileId='two';const other=api('/api/projects');assert.equal(calls,2);
 releases.splice(0).forEach(release=>release());await Promise.all([...reads,other]);
 const next=api('/api/projects');assert.equal(calls,3,'completed reads must not be cached');
 releases.shift()();await next;
 const writes=[api('/api/example','POST',{}),api('/api/example','POST',{})];assert.equal(calls,5);
 releases.splice(0).forEach(release=>release());await Promise.all(writes);
 assert.equal(api.reads.size,0,'completed requests must release their entries');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stalled_headers_and_body_release_requests_and_invalid_json_fails(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        api = 'async function api(' + source.split('async function api(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert = require('node:assert/strict');
const state={profileId:'default',project:{name:'demo'}};
const location={search:''};
let timer,cleared=0,mode='headers',signal;
const setTimeout=(fn)=>{timer=fn;return 1;};
const clearTimeout=()=>{cleared++;};
const abortable=()=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(signal.reason)));
const fetch=async(path,options)=>{
 signal=options.signal;
 if(mode==='headers') return abortable();
 if(mode==='body') return {ok:true,json:abortable};
 if(mode==='invalid') return {ok:true,json:async()=>{throw new SyntaxError('bad JSON');}};
 if(mode==='http') return {ok:false,status:503,statusText:'Unavailable',json:async()=>({error:'Busy'})};
 return {ok:true,json:async()=>({ok:true})};
};
'''+api+r'''
(async()=>{
 for(mode of ['headers','body']){
   const request=api('/api/project/demo','PUT',{});
   await Promise.resolve(); timer();
   await assert.rejects(request,/timed out/i);
   assert.equal(signal.aborted,true);
 }
 mode='invalid';await assert.rejects(api('/api/example'),/invalid.*response/i);
 mode='http';await assert.rejects(api('/api/example'),/Busy/);
 mode='success';assert.deepEqual(await api('/api/example'),{ok:true});
 assert.equal(cleared,5,'every request releases its deadline timer');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
