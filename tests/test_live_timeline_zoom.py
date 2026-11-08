import json
import subprocess
import unittest
from pathlib import Path


class LiveTimelineZoom(unittest.TestCase):
    def test_zoom_projection_and_buffer_bounds(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/live.js').read_text()
        names = ['bufferView', 'place', 'valueAt', 'syncRanges']
        functions = '\n'.join('function ' + name + source.split('function ' + name, 1)[1].split('\n}\n', 1)[0] + '\n}' for name in names)
        harness = r'''
const assert=require('assert'),vm=require('vm');
const live={isLive:true,viewSeconds:60,ranges:[{start:100,end:200},{start:4930,end:4950},{start:4970,end:4980}]};
let available={lo:1400,hi:5000};
const box=()=>({style:{},querySelector:()=>({textContent:''})});const boxes=[box(),box(),box()];
const elements={bufTrack:{getBoundingClientRect:()=>({left:100,width:1000})},bufRanges:{children:boxes}};
const context={live,domain:()=>available,liveEl:id=>elements[id],rangeBox(){throw Error('should reuse boxes');}};
vm.createContext(context);vm.runInContext(SOURCE,context);
assert.equal(vm.runInContext('bufferView(domain()).lo',context),4940);
live.viewSeconds=300;assert.equal(vm.runInContext('bufferView(domain()).lo',context),4700);
live.viewSeconds=900;assert.equal(vm.runInContext('bufferView(domain()).lo',context),4100);
live.viewSeconds=3600;assert.equal(vm.runInContext('bufferView(domain()).lo',context),1400);
live.viewSeconds=0;assert.equal(vm.runInContext('bufferView(domain()).lo',context),1400);
live.isLive=false;live.viewSeconds=60;assert.equal(vm.runInContext('bufferView(domain()).lo',context),1400);
live.isLive=true;available={lo:4980,hi:5000};
assert.equal(vm.runInContext('valueAt({clientX:100})',context),4980);
assert.equal(vm.runInContext('valueAt({clientX:1100})',context),5000);
assert.equal(vm.runInContext('valueAt({clientX:1000})',context),4994);
const shade={style:{}};context.shade=shade;vm.runInContext('place(shade,bufferView(domain()),domain().lo,domain().hi)',context);
assert(Math.abs(parseFloat(shade.style.left)-66.6666666667)<1e-6);
const original=JSON.stringify(live.ranges);vm.runInContext('syncRanges(bufferView(domain()))',context);
assert(boxes[0].hidden);assert(!boxes[1].hidden);assert(!boxes[2].hidden);assert.equal(JSON.stringify(live.ranges),original);
assert.equal(parseFloat(boxes[1].style.left),0);
console.log('Zoom windows, available shading, and seek bounds passed');
'''
        result = subprocess.run(['node', '-e', 'const SOURCE=' + json.dumps(functions) + ';\n' + harness], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Zoom windows, available shading, and seek bounds passed', result.stdout)
