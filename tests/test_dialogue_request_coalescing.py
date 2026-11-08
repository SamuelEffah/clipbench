import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class DialogueRequestCoalescingTests(unittest.TestCase):
    def test_only_newest_waiting_query_runs_and_clear_discards_pending(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/dialogue.js').read_text()
        source = source[source.index('let dialoguePending'):source.index('refreshUnheard();', source.index('let dialoguePending'))]
        script = r'''
const assert = require('node:assert/strict');
let dialogue={q:'first',results:[],busy:false}, dialogueSeq=0, dialogueTimer=0, project='one';
const projectQuery=()=>'?project='+project,paintDialogue=()=>{},toast=()=>{throw Error('stale error toast')};
const nodes={},$=id=>nodes[id]||(nodes[id]={focus(){},click(){this.onclick()}});
const setTimeout=()=>1,clearTimeout=()=>{},DIALOGUE_DELAY=250;
const calls=[],pending=[];
const api=url=>{calls.push(url);return new Promise((resolve,reject)=>pending.push({resolve,reject}));};
const result=value=>({results:[value],videos:1,unheard:[]});
const tick=()=>new Promise(setImmediate);
''' + source + r'''
(async()=>{
 const first=runDialogue();
 for(let i=0;i<50;i++){dialogue.q='query'+i;runDialogue();}
 assert.equal(calls.length,1);
 pending.shift().resolve(result('stale'));await tick();
 assert.equal(calls.length,2);assert(calls[1].includes('query49'));
 assert.deepEqual(dialogue.results,[]);
 pending.shift().resolve(result('latest'));await first;
 assert.deepEqual(dialogue.results,['latest']);
 dialogue.q='third';const third=runDialogue();dialogue.q='queued';runDialogue();
 $('dclear').onclick();pending.shift().reject(Error('old'));await third;
 assert.equal(calls.length,3);assert.deepEqual(dialogue.results,[]);
 dialogue.q='old project';const old=runDialogue();project='two';dialogue.q='new project';runDialogue();
 pending.shift().resolve(result('wrong project'));await tick();
 assert(calls.at(-1).includes('project=two'));assert.deepEqual(dialogue.results,[]);
 pending.shift().resolve(result('right project'));await old;
 assert.deepEqual(dialogue.results,['right project']);
 // Typing invalidates the active result immediately, before the debounce fires.
 dialogue.q='running';const running=runDialogue();
 $('dq').oninput({target:{value:'typing'}});
 pending.shift().resolve(result('outdated'));await running;
 assert.deepEqual(dialogue.results,['right project']);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(shutil.which('node'), 'Node required')
class UnheardCountIsPerProject(unittest.TestCase):
    def test_the_no_subtitles_count_asks_for_the_open_project_only(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/dialogue.js').read_text()
        source = source[source.index('async function refreshUnheard'):source.index('async function listenToAll')]
        script = r'''
const assert = require('node:assert/strict');
let dialogue={q:'',results:[],videos:0,unheard:[]};
const projectQuery=()=>'?project=njn',paintListen=()=>{};
const calls=[];
const api=async url=>{calls.push(url);return {videos:0,unheard:[]};};
''' + source + r'''
(async()=>{
 await refreshUnheard();
 const url=new URL('http://x'+calls[0]);
 assert.equal(url.searchParams.get('project'),'njn');
 assert.equal(url.searchParams.get('q'),'');
})().catch(e=>{console.error(e);process.exit(1);});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
