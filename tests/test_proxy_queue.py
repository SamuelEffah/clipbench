import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class ProxyQueueTests(unittest.TestCase):
    def test_requests_queue_fifo_deduplicate_and_run_one_conversion(self):
        ids = ['queue-one', 'queue-two', 'queue-three']
        entered, unexpected, release = threading.Event(), threading.Event(), threading.Event()
        calls = []
        workers_done = threading.Event()
        def convert(vid, path):
            calls.append(vid)
            if len(calls) == 1:
                entered.set()
                release.wait(2)
            else:
                unexpected.set()
            clipper.set_proxy_status(vid, {'state': 'ready', 'pct': 100})
            if len(calls) == 3:
                workers_done.set()
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.object(clipper, 'PROXY_DIR', Path(folder)), \
             mock.patch.dict(clipper.registry, {vid: Path(folder) / vid for vid in ids}), \
             mock.patch.object(clipper, 'run_proxy', side_effect=convert):
            try:
                clipper.start_proxy(ids[0])
                self.assertTrue(entered.wait(1))
                for vid in ids[1:]:
                    self.assertEqual(clipper.start_proxy(vid)['state'], 'working')
                clipper.start_proxy(ids[1])
                self.assertFalse(unexpected.wait(.1), 'another converter started while the first was busy')
            finally:
                release.set()
                workers_done.wait(2)
                for vid in ids:
                    clipper.proxies.pop(vid, None)
            self.assertEqual(calls, ids)

    def test_unexpected_failure_reports_error_and_does_not_block_next_job(self):
        ids = ['queue-failure', 'queue-after-failure']
        done = threading.Event()
        def convert(vid, path):
            if vid == ids[0]:
                raise OSError('disk failed')
            clipper.set_proxy_status(vid, {'state': 'ready', 'pct': 100})
            done.set()
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.object(clipper, 'PROXY_DIR', Path(folder)), \
             mock.patch.dict(clipper.registry, {vid: Path(folder) / vid for vid in ids}), \
             mock.patch.object(clipper, 'run_proxy', side_effect=convert), \
             self.assertLogs(clipper.log, level='ERROR'):
            try:
                for vid in ids:
                    clipper.start_proxy(vid)
                self.assertTrue(done.wait(1))
                self.assertEqual(clipper.proxy_status(ids[0])['state'], 'error')
                self.assertEqual(clipper.proxy_status(ids[1])['state'], 'ready')
            finally:
                for vid in ids:
                    clipper.proxies.pop(vid, None)
