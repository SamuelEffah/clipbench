import unittest
from tests.test_workflow_tools import UI, run_js


class PresetsAndReview(unittest.TestCase):
    def test_presets_exclude_media_and_apply_only_to_short_top_lane(self):
        source = (UI / 'panels.js').read_text().split('// Browser-local recipes', 1)[1].split('\n', 1)[1].split('// Per-clip grading', 1)[0]
        run_js(r'''
const assert=require('assert');const nodes={};const $=id=>nodes[id]||(nodes[id]={value:'',replaceChildren(){},close(){}});
const store=new Map();const localStorage={getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)};
const Option=function(n,v){this.value=v};let changes=0;const changed=()=>changes++,toast=()=>{};
const isTop=c=>!c.lane||c.lane==='top',inShort=()=>false;
const original={src:'private.mp4',in:1,out:8,caption:'private words',capLook:'pop',capScale:1.4};
const lower={src:'broll',lane:'bottom',capLook:'clean'};
const state={project:{name:'private',layout:'split',watermark:false,audio:[{src:'private.mp3'}],clips:[{src:'bank'}],other:[original,lower]}};
const timelineOf=()=>state.project.other;
''' + source, r'''
$('shortPresetName').value='My style';$('shortPresetSave').onclick();
const saved=readShortPresets()[0];assert.equal(saved.settings.layout,'split');assert.equal(saved.caption.capLook,'pop');
assert(!JSON.stringify(saved).includes('private'));assert(!('audio' in saved.settings));
state.project={...state.project,layout:'title',other:[{...original,capLook:'clean'},lower]};
$('shortPresetList').value='My style';$('shortPresetList').onchange();
assert.equal(state.project.layout,'split');assert.equal(state.project.other[0].capLook,'pop');assert.equal(state.project.other[0].caption,'private words');assert.equal(state.project.other[1],lower);assert.equal(state.project.clips[0].src,'bank');assert.equal(changes,1);
store.set('clipbench.shortPresets','broken');assert.deepEqual(readShortPresets(),[]);
''')

    def test_kept_batch_is_one_edit_and_does_not_duplicate_existing_clips(self):
        source=(UI/'suggest.js').read_text().split('function suggestionKey',1)[1].split('function paintSuggest',1)[0]
        run_js(r'''
const assert=require('assert');let changes=0,cuts=0;const changed=()=>changes++,requestCut=()=>cuts++,paintSuggest=()=>{},toast=()=>{};
const state={current:{id:1},project:{clips:[]}};
const suggestion={vid:1,clips:[{in:1,out:4},{in:5,out:9},{in:10,out:15}]};
const suggestClip=s=>({...s,src:'video'}),suggestClips=s=>[suggestClip(s)],suggestAdded=s=>state.project.clips.some(c=>c.in===s.in&&c.out===s.out);
'''+'function suggestionKey'+source,r'''
suggestionReview.set('1:4','keep');suggestionReview.set('5:9','skip');suggestionReview.set('10:15','keep');
addKeptSuggestions();assert.equal(changes,1);assert.equal(cuts,2);assert.deepEqual(state.project.clips.map(c=>c.in),[1,10]);
addKeptSuggestions();assert.equal(changes,1);assert.equal(cuts,2);
state.current.id=2;addKeptSuggestions();assert.equal(changes,1);
''')

    def test_history_refreshes_suggestion_status_after_undo(self):
        source = (UI / 'app.js').read_text().split('function travel(', 1)[1].split('const undo =', 1)[0]
        run_js(r"""
const assert=require('assert');let edits={},committed,lastEdit,editCount=0,unsaved,saveTimer;
const state={project:{clips:[{src:'added'}]},sel:0};let painted=0;
const $=()=>({}),save=()=>{},render=()=>{},toast=()=>{},paintSuggest=()=>painted++;
const setTimeout=()=>0,clearTimeout=()=>{};
""" + 'function travel(' + source, r"""
travel([{clips:[]}],[], 'undo');assert.equal(state.project.clips.length,0);assert.equal(painted,1);
""")
