import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class ShortCardProgressReuseTests(unittest.TestCase):
    def test_upload_percentage_updates_keep_cards_buttons_and_current_click_data(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/shorts.js').read_text()
        def function(name):
            return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
let created=0,opened;
const element=()=>({children:[],nodes:{},style:{},attrs:{},lastChild:{nodeValue:''},setAttribute(k,v){this.attrs[k]=v;},append(...els){this.children.push(...els);},prepend(el){this.children.unshift(el);},querySelector(q){return this.nodes[q]||=(element());}});
const document={createElement(){created++;return element();}},state={project:{name:'here'}};
const esc=String,sizeText=String,ago=()=> 'just now',agoShort=()=> 'now';
const openShort=s=>opened=s,AUTH_PROBLEM=/auth/;
''' + function('statusOf') + function('shortCard') + function('dialogRow') + r'''
let row={name:'here',folder:'001_here',title:'Title',duration:10,size:100,rendered_at:100,has_project:false,upload:{state:'uploading',pct:0}};
const card=shortCard(row),dialog=dialogRow(row);created=0;
for(let i=1;i<=4;i++){
 row={...row,upload:{state:'uploading',pct:i*10}};
 assert.equal(shortCard(row),card,'upload progress must reuse the Short card');
 assert.equal(dialogRow(row),dialog,'upload progress must reuse the dialog row');
 assert.equal(card.querySelector('.smt').textContent,`Uploading, ${i*10}%, 10s, now`);
 assert.equal(dialog.querySelector('.prog').attrs['aria-valuenow'],i*10);
}
assert.equal(created,0,'percentage-only changes should create no elements');
card.children[0].onclick();assert.equal(opened,row);
dialog.querySelector('.acts').children[0].onclick();assert.equal(opened,row);
const finished={...row,upload:{state:'done',studio_url:'https://example.com/studio',finished_at:200}};
assert.notEqual(shortCard(finished),card,'completion must refresh available actions');
assert.notEqual(dialogRow(finished),dialog);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
