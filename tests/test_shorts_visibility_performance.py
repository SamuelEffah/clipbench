import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class ShortsVisibilityPerformance(unittest.TestCase):
    def test_hidden_list_and_dialog_do_no_requests_or_reschedule_polling(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/shorts.js').read_text()
        script = r'''
const assert=require('node:assert/strict');
const events={},document={hidden:true,addEventListener(k,fn){events[k]=fn},createElement(){return {}}};
const nodes={},$=id=>nodes[id]||(nodes[id]={open:false,children:[],addEventListener(){},showModal(){this.open=true},replaceChildren(...rows){this.children=rows}});
let currentTab='shorts',renderJob=null;
const state={project:{name:'alpha'}};
const timers=new Map();let serial=0,paints=0;
const setTimeout=fn=>{timers.set(++serial,fn);return serial},clearTimeout=id=>timers.delete(id);
const calls=[],pending=[];
const api=url=>{calls.push(url);if(url==='/api/video-stats')return Promise.resolve({});return new Promise((resolve,reject)=>pending.push({resolve,reject}))};
const lists=()=>calls.filter(u=>u==='/api/shorts').length;
const watchdog=setInterval(()=>{console.error('fixture stalled');process.exit(1)},2000);
''' + source + r'''
paintShorts=()=>paints++;paintShortsBadge=()=>paints++;
(async()=>{
 const hidden=[];
 for(let i=0;i<60;i++) hidden.push(refreshShorts(true),openShortsDialog(true));
 assert.equal(calls.length,0);await Promise.all(hidden);
 assert.equal(paints,0);assert.equal(timers.size,0);
 document.hidden=false;const visible=events.visibilitychange();
 assert.equal(lists(),1);
 pending.shift().resolve([{name:'alpha',upload:{state:'uploading'}}]);await visible;
 assert.equal(paints,2);assert.equal(timers.size,1);
 document.hidden=true;events.visibilitychange();assert.equal(timers.size,0);
 document.hidden=false;const returned=events.visibilitychange();
 document.hidden=true;events.visibilitychange();
 pending.shift().resolve([{name:'alpha',upload:{state:'done'}}]);await returned;
 assert.equal(paints,2);assert.equal(timers.size,0,'hidden completion must not restart polling');
 // An open dialog refreshes on return, without touching the DOM if hidden during its request.
 $('shortsDlg').open=true;document.hidden=false;
 const dialog=events.visibilitychange();assert.equal(lists(),3);
 document.hidden=true;events.visibilitychange();pending.shift().resolve([]);await dialog;
 assert.equal(timers.size,0);assert.equal(paints,2);
 $('shortsDlg').open=false;currentTab='clip';
 document.hidden=false;const badge=events.visibilitychange();
 pending.shift().resolve([]);await badge;
 assert.equal(paints,4);assert.equal(timers.size,0);
})().catch(e=>{console.error(e);process.exitCode=1}).finally(()=>clearInterval(watchdog));
'''
        out = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
