import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class ProjectSort(unittest.TestCase):
    def test_project_sorting_handles_numeric_names_ties_and_preserves_input(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/studio.js').read_text()
        function = 'function sortProjects(' + source.split('function sortProjects(', 1)[1].split("  const sortLabels", 1)[0]
        script = r'''
const assert=require('node:assert/strict');
const projects=[{name:'Take 10',updated_at:20,clips:2},{name:'take 2',updated_at:20,clips:7},{name:'Alpha',updated_at:40,clips:2}];
const original=JSON.stringify(projects);
''' + function + r'''
const names=sort=>sortProjects(projects,sort).map(p=>p.name);
assert.deepEqual(names('recent'),['Alpha','take 2','Take 10']);
assert.deepEqual(names('name-asc'),['Alpha','take 2','Take 10']);
assert.deepEqual(names('name-desc'),['Take 10','take 2','Alpha']);
assert.deepEqual(names('clips'),['take 2','Alpha','Take 10']);
assert.equal(JSON.stringify(projects),original);
assert.deepEqual(sortProjects([],'recent'),[]);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
