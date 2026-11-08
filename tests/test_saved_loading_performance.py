import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class SavedLoadingPerformance(unittest.TestCase):
    def test_cut_completions_batch_rendering_and_cached_cuts_need_no_work(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        load = 'async function loadAssets(' + source.split('async function loadAssets(', 1)[1].split('\nasync function refreshLibrary(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let renders=0,requests=0,refreshes=0,fail=false;
const state={favorites:[]},favorites=Array.from({length:300},(_,i)=>({id:String(i)}));
const cutIds=new Map(),cutKey=c=>c.id,projectQuery=()=>'?project=test';
const refreshLibrary=async()=>refreshes++,api=async()=>{if(fail)throw Error('offline');return favorites;};
const pending=new Map();
const requestCut=c=>{requests++;return cutIds.has(c.id)?Promise.resolve(cutIds.get(c.id)):new Promise(resolve=>pending.set(c.id,resolve));};
const renderFavs=()=>renders++;
const frames=[];const requestAnimationFrame=fn=>{frames.push(fn);return frames.length;};
const flush=async()=>{await Promise.resolve();await Promise.resolve();};
''' + load + r'''
(async()=>{
await loadAssets();assert.equal(renders,1);assert.equal(requests,300);assert.equal(refreshes,1);
for(const [id,resolve] of pending){cutIds.set(id,id);resolve(id);}
await flush();assert.equal(renders,1,'completions wait for the next paint');assert.equal(frames.length,1,'one frame for a burst of 300 completions');
frames.shift()();assert.equal(renders,2);
requests=0;renders=0;await loadAssets();await flush();
assert.equal(requests,0,'cached cuts are already represented by the initial render');assert.equal(renders,1);assert.equal(frames.length,0);
// Failed preparation does not repaint; later successful bursts each schedule one fresh frame.
cutIds.clear();pending.clear();renders=0;await loadAssets();
pending.get('0')(null);await flush();assert.equal(frames.length,0);
pending.get('1')('ready');await flush();assert.equal(frames.length,1);frames.shift()();
pending.get('2')('ready');pending.get('3')('ready');await flush();assert.equal(frames.length,1);frames.shift()();assert.equal(renders,3);
fail=true;await loadAssets();assert.deepEqual(state.favorites,[]);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
