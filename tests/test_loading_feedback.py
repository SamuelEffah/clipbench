import shutil
import subprocess
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'


@unittest.skipUnless(shutil.which('node'), 'Node required')
class LoadingFeedback(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run(['node', '-e', code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_download_ignores_duplicate_requests_and_can_retry_after_failure(self):
        app = (UI / 'app.js').read_text()
        functions = 'let downloading = false' + app.split('let downloading = false', 1)[1].split('$("dlBtn").onclick', 1)[0]
        self.run_js(r'''
const assert=require('node:assert/strict');
const nodes=new Map();const $=id=>{if(!nodes.has(id))nodes.set(id,{value:'https://example.com/video',style:{},attrs:{},classes:{},classList:{toggle(k,v){nodes.get(id).classes[k]=v;}},setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];},focus(){},close(){this.closed=true;}});return nodes.get(id);};
let reject,requests=0,refreshes=0,opened;
const state={project:{name:'original'},library:[{path:'video',id:1}]};
let answer=()=>new Promise((_,fail)=>{reject=fail;});
const api=()=>{requests++;return answer();};
const refreshLibrary=async()=>refreshes++,openVideo=v=>opened=v,toast=()=>{};
''' + functions + r'''
(async()=>{
 const pending=startDownload();await startDownload();assert.equal(requests,1);
 assert.equal($('dlGo').disabled,true);assert.equal($('dlUrl').readOnly,true);
 assert.equal($('dlBar').classes.indeterminate,true);assert.equal($('dlBar').attrs['aria-valuenow'],undefined);
 reject(new Error('Connection lost'));await pending;
 assert.equal($('dlGo').textContent,'Retry download');assert.equal($('dlGo').disabled,false);assert.equal($('dlUrl').readOnly,false);
 assert.equal($('dlUrl').value,'https://example.com/video');assert.equal($('dlStatus').textContent,'Connection lost');
 answer=async()=>({state:'done',file:'video'});await startDownload();
 assert.equal(requests,2);assert.equal(refreshes,1);assert.equal(opened.id,1);assert.equal($('dlDlg').closed,true);
 assert.equal($('dlGo').textContent,'Download');assert.equal($('dlBar').hidden,true);
})().catch(e=>{console.error(e);process.exit(1);});
''')

    def test_stream_failure_releases_controls_and_allows_retry(self):
        live = (UI / 'live.js').read_text()
        feedback = 'let liveConnecting = false' + live.split('let liveConnecting = false', 1)[1].split('// Browsers refuse', 1)[0]
        loading = 'let liveLoadToken = 0;' + live.split('let liveLoadToken = 0;', 1)[1].split('// Twitch keeps', 1)[0]
        self.run_js(r'''
const assert=require('node:assert/strict');
const nodes=new Map();const liveEl=id=>{if(!nodes.has(id))nodes.set(id,{value:'https://youtube.com/watch?v=example',dataset:{},attrs:{},classList:{toggle(){}},setAttribute(k,v){this.attrs[k]=v;}});return nodes.get(id);};
let reject,attempts=0;
const liveSource=()=>({kind:'youtube',id:'example'});
const live={};const destroyLive=()=>{},mount=()=>{};
const youtubeApi=()=>{attempts++;return new Promise((_,fail)=>{reject=fail;});};
''' + feedback + loading + r'''
(async()=>{
 const pending=openLive();await openLive();assert.equal(attempts,1);
 assert.equal(liveEl('liveLoad').disabled,true);assert.equal(liveEl('liveFeedback').dataset.state,'loading');
 reject(new Error('Player unavailable'));await pending;
 assert.equal(liveEl('liveLoad').disabled,false);assert.equal(liveEl('liveUrl').readOnly,false);
 assert.equal(liveEl('liveRetry').hidden,false);assert.equal(liveEl('liveFeedback').dataset.state,'error');
 const retry=openLive();assert.equal(attempts,2);assert.equal(liveEl('liveRetry').hidden,true);
 reject(new Error('Still unavailable'));await retry;
 assert.equal(liveEl('liveHint').textContent,'Still unavailable');
})().catch(e=>{console.error(e);process.exit(1);});
''')
