import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class HiddenLibraryPanelsPerformance(unittest.TestCase):
    def test_hidden_lists_skip_cards_and_tabs_render_current_state(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        def function(name):
            return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        code = ''.join(function(name) for name in ['momentFinder', 'momentLookup', 'sourceRowsSummary', 'renderLibrary', 'renderFavs', 'setSideTab'])
        script = r'''
const assert=require('node:assert/strict');
let created=0,reads=0,favFilter='';
const element=()=>({children:[],hidden:true,attrs:{},set innerHTML(v){this.html=v;this.children=[];},get innerHTML(){return this.html;},appendChild(el){this.children.push(el);},querySelector:()=>element(),setAttribute(k,v){this.attrs[k]=v;}});
const ids=new Map(),$=id=>{if(!ids.has(id))ids.set(id,element());return ids.get(id);};
const document={createElement:()=>{created++;return element();}};
const sources=Array.from({length:300},(_,i)=>({id:String(i),path:`v${i}`,name:`Video${i}`,duration:10}));
const state={current:null,library:sources,favorites:sources.map(v=>({src:v.path,in:0,out:5})),project:{clips:sources.map(v=>({get src(){reads++;return v.path;},in:0,out:5}))}};
const renderSourceWelcome=()=>{},streaming=()=>false,sourceDisplayName=String;
const sourcesOf=()=>sources,liveRowWanted=()=>false,byPath=src=>sources.find(v=>v.path===src);
const esc=String,fmt=String,mmss=String,clipName=c=>c.src,outLen=c=>c.out-c.in,volumeOf=c=>c.volume??1;
const cutIds=new Set(),cutKey=c=>c.src,sameMoment=(a,b)=>a.src===b.src&&Math.abs(a.in-b.in)<.05&&Math.abs(a.out-b.out)<.05;
''' + code + r'''
renderLibrary();renderFavs();assert.equal(created,0);assert.equal(reads,300);assert.ok($('tabMedia').innerHTML.includes('300'));
setSideTab('media');assert.equal($('library').children.length,300);assert.equal(created,300);assert.ok($('library').children[0].innerHTML.includes('1 clip</span>'));
setSideTab('fav');assert.equal($('favList').children.length,300);assert.ok($('favList').children[0].innerHTML.includes('In Short'));
const oldLibrary=$('library').children,oldSaved=$('favList').children;
setSideTab('fx');created=0;reads=0;
state.project.clips=[];sources.push({id:'new',path:'new',name:'New',duration:1});state.favorites=[{src:'new',in:0,out:1}];
for(let i=0;i<120;i++){renderLibrary();renderFavs();}
assert.equal(created,0);assert.equal(reads,0);assert.equal($('library').children,oldLibrary);assert.equal($('favList').children,oldSaved);
setSideTab('media');assert.equal($('library').children.length,301);assert.ok($('library').children[0].innerHTML.includes('0 clips'));
setSideTab('fav');assert.equal($('favList').children.length,1);assert.ok(!$('favList').children[0].innerHTML.includes('In Short'));
// Clearing Saved while hidden still resets its search and opens with the empty message.
setSideTab('fx');favFilter='old search';state.favorites=[];renderFavs();assert.equal(favFilter,'');assert.equal($('favSearch').value,'');
setSideTab('fav');assert.ok($('favList').innerHTML.includes('Nothing saved yet'));
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
