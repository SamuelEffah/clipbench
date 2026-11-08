import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class ShortsPollOwnership(unittest.TestCase):
    def test_open_dialog_owns_polling_and_closing_resumes_the_tab(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/shorts.js').read_text()
        script = r'''
const assert=require('node:assert/strict');
const document={hidden:true,addEventListener(){},createElement(){return {}}};
const nodes={},$=id=>nodes[id]||(nodes[id]={open:false,children:[],events:{},
 addEventListener(k,fn){this.events[k]=fn},showModal(){this.open=true},replaceChildren(...rows){this.children=rows}});
let currentTab='shorts',renderJob=null;
const state={project:{name:'alpha'}},timers=new Map();let serial=0,requests=0;
const setTimeout=fn=>{timers.set(++serial,fn);return serial},clearTimeout=id=>timers.delete(id);
const row={name:'alpha',upload:{state:'uploading',pct:20}};
const api=async url=>{if(url==='/api/video-stats')return {};requests++;return url==='/api/shorts'?[row]:{alpha:row.upload}};
''' + source + r'''
paintShorts=()=>{};paintShortsBadge=()=>{};
dialogRow=s=>{const node={};(dialogRow.cache ||= new Map()).set(s.name,{node});return node};
(async()=>{
 document.hidden=false;await openShortsDialog(true);
 assert.equal(requests,1);assert.equal(timers.size,1,'dialog and tab must not each schedule a poll');
 for(let i=0;i<20;i++){
  const [id,fn]=[...timers][0];timers.delete(id);fn();await new Promise(setImmediate);
  assert.equal(timers.size,1);
 }
 assert.equal(requests,21,'one request per polling cycle is sufficient for both views');
 $('shortsDlg').open=false;await $('shortsDlg').events.close();
 assert.equal(timers.size,1);assert.equal(requests,22,'closing refreshes and resumes the tab');
 const [id,fn]=[...timers][0];timers.delete(id);await fn();
 assert.equal(requests,23);assert.equal(timers.size,1);
 document.hidden=true;$('shortsDlg').open=true;
 await $('shortsDlg').events.close();assert.equal(requests,23,'closing while hidden must not fetch');
 document.hidden=false;shorts.rows=[{...row,upload:{state:'done'}}];
 await $('shortsDlg').events.close();assert.equal(requests,23,'completed uploads need no resumed poll');
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        out = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
