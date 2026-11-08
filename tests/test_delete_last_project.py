import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class DeleteLastProject(unittest.TestCase):
    def test_last_delete_does_not_save_replacement_and_waits_for_existing_save(self):
        source=(Path(__file__).resolve().parents[1]/'scripts/clipper_ui/app.js').read_text()
        delete='async function deleteProject('+source.split('async function deleteProject(',1)[1].split('// A new project',1)[0]
        script=r'''
const assert=require('node:assert/strict');
let returnToProjectsAfterDelete=true, unsaved=true, saveTimer=null, projectNames=['only'];
const state={project:{name:'only'}};
const events=[];
const $=()=>({close(){},textContent:''});
const api=async()=>events.push('delete');
const save={running:Promise.resolve().then(()=>events.push('save finished'))};
const flushSave=async()=>{};
const createProject=async(name,persist=true)=>{assert.equal(persist,false,'last delete must leave an unsaved draft');events.push('draft');};
let sessionReady=true;
const preview={on:false},video={pause(){}};
const window={location:{assign:url=>events.push('navigate:'+url)}};
const loadProject=async()=>{},toast=()=>{},paintProjects=()=>{},projDlg={open:false};
const localStorage={removeItem(){}};
const LAST_PROJECT_KEY='last';
''' + delete + r'''
(async()=>{await deleteProject('only');assert.deepEqual(projectNames,[]);assert.ok(events.indexOf('save finished')<events.indexOf('delete'));assert.ok(events.includes('navigate:/'));assert.equal(sessionReady,false);assert.ok(!events.includes('draft'));})().catch(e=>{console.error(e);process.exitCode=1});
'''
        out=subprocess.run(['node','-e',script],capture_output=True,text=True)
        self.assertEqual(out.returncode,0,out.stderr)
