import json
import subprocess
import unittest
from pathlib import Path


class CaptionWordMotion(unittest.TestCase):
    def test_highlights_reuse_phrase_nodes_and_reset_after_static_or_empty(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/captions.js').read_text()
        source = 'function paintCaption(' + source.split('function paintCaption(', 1)[1].split('// New text', 1)[0]
        harness = r'''
const assert=require('assert'),vm=require('vm');let created=0,replaced=0,writes=0;
const document={createElement(){created++;return {textContent:'',get className(){return this.cls;},set className(value){writes++;this.cls=value;}};}};
const el={dataset:{},textContent:'',replaceChildren(...nodes){this.children=nodes;replaced++;}};
const context={document,el};vm.createContext(context);vm.runInContext(SOURCE,context);
const words=['Stay','with','me'];const paint=lit=>{context.cap={key:'phrase|'+lit,words,lit};vm.runInContext('paintCaption(el,cap)',context);};
paint(0);assert.equal(created,3);assert.equal(replaced,1);const original=[...el._captionSpans];
created=replaced=writes=0;paint(1);assert.equal(created,0);assert.equal(replaced,0);assert.equal(writes,2);assert.equal(el._captionSpans[0],original[0]);assert.equal(original[0].className,'caption-word');assert.equal(original[1].className,'caption-word lit');
writes=0;for(let i=0;i<120;i++)paint(1);assert.equal(writes,0);assert.equal(replaced,0);
vm.runInContext('paintCaption(el,{key:"static",words:["Static caption"],lit:-1})',context);assert.equal(el.textContent,'Static caption');assert.equal(el._captionSpans,null);
paint(2);assert.equal(created,3);assert.equal(el._captionSpans[2].className,'caption-word lit');
vm.runInContext('paintCaption(el,null)',context);assert.equal(el.textContent,'');assert.equal(el._captionSpans,null);
paint(0);assert.equal(created,6);
console.log('Stable caption phrase and word highlights passed');
'''
        result = subprocess.run(['node', '-e', 'const SOURCE=' + json.dumps(source) + ';\n' + harness], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Stable caption phrase and word highlights passed', result.stdout)
