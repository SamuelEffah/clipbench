import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class ShortsProgressApiTests(unittest.TestCase):
    def test_progress_endpoint_reads_upload_states_without_scanning_files(self):
        handler = object.__new__(clipper.Handler)
        handler.host_ok = lambda: True
        handler.path = '/api/uploads/progress?name=alpha&name=beta&name=alpha'
        handler.send_json = mock.Mock()
        publisher = mock.Mock()
        publisher.state.side_effect = lambda name: {'state': 'uploading', 'pct': len(name)}
        with mock.patch.object(clipper, 'publisher', publisher), \
             mock.patch.object(clipper, 'list_shorts') as scan, \
             mock.patch.object(clipper, 'short_folder') as folder:
            handler.do_GET()
        handler.send_json.assert_called_once_with({'alpha': {'state': 'uploading', 'pct': 5}, 'beta': {'state': 'uploading', 'pct': 4}})
        self.assertEqual(publisher.state.call_count, 2)
        scan.assert_not_called()
        folder.assert_not_called()

    def test_invalid_names_are_rejected_before_reading_uploads(self):
        handler = object.__new__(clipper.Handler)
        handler.host_ok = lambda: True
        handler.path = '/api/uploads/progress?name=../outside'
        handler.send_json = mock.Mock()
        publisher = mock.Mock()
        with mock.patch.object(clipper, 'publisher', publisher):
            handler.do_GET()
        self.assertEqual(handler.send_json.call_args.args[1], 400)
        publisher.state.assert_not_called()


@unittest.skipUnless(shutil.which('node'), 'Node required')
class ShortsProgressPollingTests(unittest.TestCase):
    def test_progress_polls_skip_full_list_until_terminal_or_periodic_refresh(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/shorts.js').read_text()
        code = 'async function refreshShorts(' + source.split('async function refreshShorts(', 1)[1].split('\nasync function openShort(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let now=100000,full=0,progress=0,pct=0,done=false,timer;
const document={hidden:false};
const Date={now:()=>now},shorts={rows:[]},currentTab='shorts';
const api=async path=>{
 if(path==='/api/shorts'){full++;return [{name:'alpha',upload:{state:done?'done':'uploading',pct}}];}
 assert.ok(path.startsWith('/api/uploads/progress?'));progress++;return {alpha:{state:done?'done':'uploading',pct}};
};
const paintShorts=()=>{},paintShortsBadge=()=>{},clearTimeout=()=>{},setTimeout=fn=>{timer=fn;},$=()=>({});
''' + code + r'''
(async()=>{
 await refreshShorts();assert.equal(full,1);
 for(let i=1;i<=4;i++){now+=1500;pct=i*10;await timer();assert.equal(shorts.rows[0].upload.pct,pct);}
 assert.equal(full,1,'progress polls must not rescan all rendered folders');assert.equal(progress,4);
 done=true;now+=1500;await timer();assert.equal(full,2,'terminal state refresh must validate rendered-file metadata');
 done=false;await refreshShorts();now+=11000;await timer();assert.equal(full,4,'periodic refresh discovers external metadata changes');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
