import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class AudioLibraryDomPerformance(unittest.TestCase):
    def test_playback_reuses_groups_and_unaffected_rows(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/audio.js').read_text()
        source = source[source.index('// Songs and effects as folding sections'):source.index('\nfunction uploadAudio')]
        script = r'''
const assert=require('node:assert/strict');
let created=0,builds=0;
const element=()=>({children:[],hidden:false,replaceChildren(...rows){this.children=rows}});
const document={createElement:element};
const list=element(),$=()=>list;
const section=(title,rows,note)=>{
 builds++;const body=element(),count={textContent:note};body.children=rows;
 return {body,count,querySelector(q){return q==='.dsec-b'?body:count}};
};
let audioFiles=Array.from({length:1000},(_,i)=>({id:String(i),name:'Sound '+i,kind:i%2?'song':'sfx',duration:2}));
let libPlaying='';
const audioRow=f=>{created++;return {file:f,playing:libPlaying===f.id}};
''' + source + r'''
renderAudioLib();assert.equal(created,1000);assert.equal(builds,2);
const songs=list.children[0],effects=list.children[1];songs.body.hidden=true;
for(let i=0;i<100;i++) renderAudioLib();
assert.equal(created,1000);assert.equal(builds,2);
libPlaying='1';renderAudioLib();assert.equal(created,1001);
libPlaying='2';renderAudioLib();assert.equal(created,1003);
assert.equal(list.children[0],songs);assert.equal(list.children[1],effects);
assert.equal(songs.body.hidden,true,'fold state must survive playback');
audioFiles[0].name='Renamed';renderAudioLib();assert.equal(created,1004);
audioFiles=[{id:'new',name:'New',kind:'song',duration:40}];renderAudioLib();
assert.equal(songs.count.textContent,'1');assert.equal(effects.count.textContent,'0');
assert.equal(audioLibRows.size,1);
audioFiles=[];renderAudioLib();assert.equal(audioLibRows.size,0);assert.equal(list.children.length,3);
'''
        out = subprocess.run(['node', '-e', script], text=True, capture_output=True)
        self.assertEqual(out.returncode, 0, out.stderr)
