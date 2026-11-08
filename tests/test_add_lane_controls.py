import json
import subprocess
import unittest
from pathlib import Path


class AddLaneControls(unittest.TestCase):
    def test_video_add_limit_preserves_media_and_audio_opens_library(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/lanes.js').read_text().split('function addVideoLane()', 1)[1]
        source = 'function addVideoLane()' + source
        harness = r'''
const vm=require('vm'),assert=require('assert');let edits=0,opened='',focused=false,restarts=0;
const clips=[{lane:'top',id:'existing'}],audio=[{id:'sound'}],state={project:{template:'full',clips,audio}};
const context={state,LANES:['top','bottom','third','fourth'],laneCount:()=>({full:1,split:2,three:3,four:4}[state.project.template]),changed:()=>edits++,preview:{on:false},startPreviewAt:()=>restarts++,nextTop:()=>0,railShow:name=>opened=name,$:()=>({focus(){focused=true;}}),document:{createElement(){return {children:[],setAttribute(){},append(...nodes){this.children.push(...nodes);}};}}};
vm.createContext(context);vm.runInContext(SOURCE,context);
let controls=vm.runInContext('laneAddControls()',context);assert.equal(controls.children[0].textContent,'V');assert.equal(controls.children[1].textContent,'A');
controls.children[0].onclick();assert.equal(state.project.template,'split');assert.equal(state.project.clips,clips);assert.equal(state.project.audio,audio);
context.preview.on=true;vm.runInContext('addVideoLane();addVideoLane();addVideoLane()',context);assert.equal(state.project.template,'four');assert.equal(edits,3);assert.equal(restarts,2);
controls=vm.runInContext('laneAddControls()',context);assert(controls.children[0].disabled);
controls.children[1].onclick();assert.equal(opened,'music');assert(focused);assert.equal(edits,3);
console.log('Add lane controls passed');
'''
        result = subprocess.run(['node', '-e', 'const SOURCE=' + json.dumps(source) + ';\n' + harness], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Add lane controls passed', result.stdout)
