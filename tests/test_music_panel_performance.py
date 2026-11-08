import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class MusicPanelPerformance(unittest.TestCase):
    def test_music_render_indexes_used_files_and_instrumental_names(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        panels = (ui / 'panels.js').read_text()
        vocals = (ui / 'vocals.js').read_text()
        music = 'function paintMusic(' + panels.split('function paintMusic(', 1)[1].split('$("musicAdd").onclick', 1)[0]
        helpers = 'const isSong' + panels.split('const isSong', 1)[1].split('\nfunction paintMusic(', 1)[0]
        voice = 'const voxBusy' + vocals.split('const voxBusy', 1)[1].split('async function removeVocals(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let fileReads=0,itemReads=0,added=null,removed=null,created=0,replacements=0;
const track=list=>new Proxy(list,{get(t,k,r){if(/^\d+$/.test(String(k)))fileReads++;return Reflect.get(t,k,r);}});
let audioFiles=track(Array.from({length:2000},(_,i)=>({id:String(i),name:`Song${i}`,kind:'song',duration:30})));
let items=Array.from({length:1000},(_,i)=>({id:`a${i}`,get file(){itemReads++;return String(i*2);}}));
const audioOf=()=>items;
const element=()=>{created++;return {children:[],append(...els){this.children.push(...els);},replaceChildren(...els){replacements++;this.children=els;}}};
const list=element(),$=()=>list,document={createElement:element};
const esc=String,secs=String,preview={elapsed:2},addAudio=(...args)=>added=args,removeAudio=id=>removed=id;
const startSoundDrag=()=>{},endSoundDrag=()=>{},removeVocals=()=>{};
const musicMenu=(f,names)=>({menuFor:f.id,names});
''' + helpers + voice + music + r'''
paintMusic();assert.ok(fileReads<=6000,`${fileReads} file reads for a 2000-song panel`);assert.equal(itemReads,1000);
const built=created, replaced=replacements;
for(let i=0;i<100;i++) paintMusic();
assert.equal(created,built,'unchanged music panels must reuse rows');
assert.equal(replacements,replaced,'unchanged rows must stay attached');
items=[...items,{id:'added',file:'1'}];paintMusic();assert.equal(created,built+2);
items=items.slice(0,-1);paintMusic();
assert.equal(list.children.length,2000);const first=list.children[0].children[0],second=list.children[1].children[0];
assert.ok(first.className.includes(' on'));assert.ok(!second.className.includes(' on'));
first.onclick();assert.equal(removed,'a0');second.onclick();assert.deepEqual(added,[audioFiles[1],0]);
// Every row gets its menu; the menu reads the instrumental names and busy state when it opens, so the row key only
// has to change when what the menu offers changes. Click handlers use the current sound list.
audioFiles=track([{id:'s',name:'Song',kind:'song',duration:40},{id:'i',name:'Song (instrumental)',kind:'song',duration:40},{id:'e',name:'Effect',kind:'sfx',duration:2},{id:'b',name:'Busy',kind:'song',duration:40}]);
items=[];voxBusy.add('b');paintMusic();
assert.deepEqual([0,1,2,3].map(n=>list.children[n].className),['mrow','mrow','mrow','mrow']);
assert.equal(list.children[3].children[1].menuFor,'b');
list.children[2].children[0].onclick();assert.deepEqual(added,[audioFiles[2],2]);
items=[{id:'later',file:'s'}];list.children[0].children[0].onclick();assert.equal(removed,'later');
audioFiles=[];paintMusic();assert.ok(list.innerHTML.includes('No music yet'));
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
