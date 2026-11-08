import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class ReframeAnalysisReuseTests(unittest.TestCase):
    def api(self, src, start, end):
        handler = object.__new__(clipper.Handler)
        handler.host_ok = handler.origin_ok = lambda: True
        handler.path = '/api/reframe'
        handler.read_json = lambda: {'src': src, 'in': start, 'out': end}
        result = []
        handler.send_json = lambda data, status=200: result.append((data, status))
        handler.do_POST()
        self.assertEqual(result[0][1], 200)
        return result[0][0]

    def test_matching_requests_share_analysis_and_versions_and_ranges_invalidate(self):
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder) / 'source.mp4'
            src.write_bytes(b'source')
            found = {'found': True, 'face': {'x': .5}, 'samples': [{'t': 0, 'x': .5, 'y': .5}], 'looked': 3}
            def detect(*args):
                time.sleep(.03)
                return found
            gate = threading.Barrier(8)
            def request(_):
                gate.wait(timeout=3)
                return self.api(str(src), 0, 3)
            with mock.patch.object(clipper, 'registry', {'source': src}), \
                 mock.patch.object(clipper.reframe, 'find_faces', side_effect=detect) as scan, \
                 mock.patch.object(clipper.reframe, 'probe_size', return_value=(1920, 1080)):
                with ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(request, range(8)))
                self.assertEqual(scan.call_count, 1, 'eight requests should decode and detect faces once')
                self.assertTrue(all(r == results[0] for r in results))
                results[0]['track'][0]['x'] = 0
                self.assertEqual(clipper.reframe_analysis(str(src), 0, 3)['track'][0]['x'], .5)
                self.assertEqual(scan.call_count, 1)
                clipper.reframe_analysis(str(src), 1, 3)
                self.assertEqual(scan.call_count, 2)
                src.write_bytes(b'changed source')
                clipper.reframe_analysis(str(src), 0, 3)
                self.assertEqual(scan.call_count, 3)

    def test_errors_and_empty_decodes_can_be_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder) / 'source.mp4'
            src.write_bytes(b'source')
            empty = {'found': False, 'face': None, 'samples': [], 'looked': 0}
            valid = {**empty, 'looked': 3}
            with mock.patch.object(clipper.reframe, 'find_faces', side_effect=[OSError('failed'), empty, valid]) as scan, \
                 mock.patch.object(clipper.reframe, 'probe_size', return_value=(1920, 1080)):
                with self.assertRaises(OSError):
                    clipper.reframe_analysis(str(src), 0, 3)
                clipper.reframe_analysis(str(src), 0, 3)
                clipper.reframe_analysis(str(src), 0, 3)
                clipper.reframe_analysis(str(src), 0, 3)
                self.assertEqual(scan.call_count, 3)
