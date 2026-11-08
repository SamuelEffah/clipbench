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
        button = 'function voxButton(' + vocals.split('function voxButton(', 1)[1]
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
''' + helpers + voice + button + music + r'''
paintMusic();assert.ok(fileReads<=6000,`${fileReads} file reads for a 2000-song panel`);assert.equal(itemReads,1000);
const built=created, replaced=replacements;
for(let i=0;i<100;i++) paintMusic();
assert.equal(created,built,'unchanged music panels must reuse rows');
assert.equal(replacements,replaced,'unchanged rows must stay attached');
items=[...items,{id:'added',file:'1'}];paintMusic();assert.equal(created,built+3);
items=items.slice(0,-1);paintMusic();
assert.equal(list.children.length,2000);const first=list.children[0].children[0],second=list.children[1].children[0];
assert.ok(first.className.includes(' on'));assert.ok(!second.className.includes(' on'));
first.onclick();assert.equal(removed,'a0');second.onclick();assert.deepEqual(added,[audioFiles[1],0]);
// An existing instrumental hides the conversion button, effects never offer it,
// busy conversions stay disabled, and click handlers use the current sound list.
audioFiles=track([{id:'s',name:'Song',kind:'song',duration:40},{id:'i',name:'Song (instrumental)',kind:'song',duration:40},{id:'e',name:'Effect',kind:'sfx',duration:2},{id:'b',name:'Busy',kind:'song',duration:40}]);
items=[];voxBusy.add('b');paintMusic();
assert.equal(list.children[0].className,'mtrack');assert.equal(list.children[1].className,'mtrack');assert.equal(list.children[2].className,'mtrack');
assert.equal(list.children[3].className,'mrow');assert.equal(list.children[3].children[1].disabled,true);
list.children[2].onclick();assert.deepEqual(added,[audioFiles[2],2]);
items=[{id:'later',file:'s'}];list.children[0].onclick();assert.equal(removed,'later');
// Standalone vocal buttons keep dynamic lookup; the next render sees removals.
assert.equal(voxButton(audioFiles[0]),null);audioFiles=track([audioFiles[0]]);paintMusic();assert.equal(list.children[0].className,'mrow');
audioFiles=[];paintMusic();assert.ok(list.innerHTML.includes('No music yet'));
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
