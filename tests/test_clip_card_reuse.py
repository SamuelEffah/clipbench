import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class ClipCardReuseTests(unittest.TestCase):
    def test_tray_bank_and_saved_reuse_unchanged_cards_and_refresh_handlers(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        def function(source, name):
            return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        app, short = (ui / 'app.js').read_text(), (ui / 'short.js').read_text()
        code = function(app, 'renderTray') + function(app, 'renderFavs') + function(short, 'renderBank')
        script = r'''
const assert=require('node:assert/strict');
let created=0,selected=-1,bankSelected=-1,renamed,added;
const make=()=>({children:[],nodes:{},style:{},classList:{add(){},remove(){}},set innerHTML(v){this.html=v;this.children=[];},get innerHTML(){return this.html;},
 appendChild(el){this.children.push(el);},querySelector(q){if(q==='.crow.sel')return this.children.find(c=>c.className.includes(' sel'))||null;return this.nodes[q]||=(make());},scrollIntoView(){}});
const ids={},$=id=>ids[id]||=(make());
const document={createElement(){created++;return make();}};
const v={name:'Source.mp4'},byPath=()=>v,clipName=()=>v.name,outLen=c=>c.out-c.in,esc=String,fmt=String,mmss=String,volumeOf=c=>c.volume??1;
const same=(a,b)=>a.src===b.src&&a.in===b.in&&a.out===b.out,momentLookup=list=>c=>list.some(f=>same(c,f));
const clips=Array.from({length:300},(_,i)=>({src:'v',in:i,out:i+1,caption:'caption '+i,note:'clip '+i}));
const state={mode:'clip',sel:-1,project:{clips},favorites:clips.map(c=>({...c})),arrived:-1};
let bank=clips.map(c=>({...c})),favFilter='';
const bankOf=()=>bank,bankSel=new Set(),bankBar=()=>make(),splitOn=()=>false,pickBank=i=>bankSelected=i;
const cutIds=new Set(),cutKey=c=>c.in,CLIP_MIME='clip',TRAY_MIME='tray';
const select=i=>selected=i,addFavorite=f=>added=f,renameFavorite=(f,label)=>renamed=[f,label];
''' + code + r'''
renderTray();const trayBefore=$('tray').children.slice();created=0;
state.project={...state.project,clips:state.project.clips.map((c,i)=>i===100?{...c,caption:'Edited'}:c)};
renderTray();assert.equal(created,1,'editing one caption must rebuild one of 300 tray cards');
for(let i=0;i<300;i++)assert.equal(trayBefore[i]===$('tray').children[i],i!==100);
created=0;renderFavs();assert.equal(created,300);const savedBefore=$('favList').children.slice();created=0;
state.favorites=state.favorites.map((f,i)=>i===100?{...f,label:'Named'}:f);renderFavs();assert.equal(created,1,'rename one Saved card');
for(let i=0;i<300;i++)assert.equal(savedBefore[i]===$('favList').children[i],i!==100);
const named=$('favList').children[100];named.nodes['.favname'].value='Again';named.nodes['.favname'].onchange();assert.equal(renamed[0],state.favorites[100]);
created=0;renderBank();assert.equal(created,300);const bankBefore=$('tray').children.slice();created=0;
bank=bank.map((c,i)=>i===100?{...c,note:'Edited'}:c);renderBank();assert.equal(created,1,'edit one bank card');
for(let i=0;i<300;i++)assert.equal(bankBefore[i]===$('tray').children[i],i!==100);
// Reorder must refresh captured indices for selection and drag operations.
state.project.clips=[state.project.clips[1],state.project.clips[0],...state.project.clips.slice(2)];renderTray();$('tray').children[1].onclick();assert.equal(selected,1);
bank=[bank[1],bank[0],...bank.slice(2)];renderBank();$('tray').children[1].onclick({target:{closest:()=>null}});assert.equal(bankSelected,1);
state.project.clips=[];renderFavs();assert.ok(!$('favList').children[0].innerHTML.includes('In Short'));
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
