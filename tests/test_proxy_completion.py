import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class ProxyCompletionTests(unittest.TestCase):
    def test_waiting_requests_wake_as_soon_as_preparation_finishes(self):
        for state in ('ready', 'error'):
            with self.subTest(state=state):
                vid = 'completion-test'
                self.addCleanup(clipper.proxies.pop, vid, None)
                clipper.proxies[vid] = {'state': 'working', 'pct': 10}
                waiting, finished = threading.Event(), threading.Event()
                result = []
                original_wait = clipper.proxy_finished.wait
                def wait(*args, **kwargs):
                    waiting.set()
                    return original_wait(*args, **kwargs)
                def request():
                    result.append(clipper.proxy_status(vid, wait=True))
                    finished.set()
                with mock.patch.object(clipper.proxy_finished, 'wait', side_effect=wait):
                    worker = threading.Thread(target=request)
                    worker.start()
                    try:
                        self.assertTrue(waiting.wait(1))
                        clipper.set_proxy_status(vid, {'state': state, 'pct': 100})
                        self.assertTrue(finished.wait(.5), 'completion must not wait for the next one-second poll')
                    finally:
                        worker.join(2)
                self.assertEqual(result[0]['state'], state)

    def test_ready_unknown_and_non_waiting_requests_return_immediately(self):
        with mock.patch.object(clipper.proxy_finished, 'wait') as wait:
            self.assertEqual(clipper.proxy_status('unknown', wait=True)['state'], 'none')
            clipper.proxies['immediate-test'] = {'state': 'ready', 'pct': 100}
            self.addCleanup(clipper.proxies.pop, 'immediate-test', None)
            self.assertEqual(clipper.proxy_status('immediate-test', wait=True)['state'], 'ready')
            clipper.proxies['immediate-test'] = {'state': 'working', 'pct': 50}
            self.assertEqual(clipper.proxy_status('immediate-test')['pct'], 50)
            wait.assert_not_called()

    def test_http_route_enables_wait_only_when_requested(self):
        handler = object.__new__(clipper.Handler)
        handler.host_ok = lambda: True
        handler.send_json = mock.Mock()
        vid = 'a' * 12
        with mock.patch.object(clipper, 'proxy_status', return_value={'state': 'ready'}) as status:
            for query, expected in [('', False), ('?wait=1', True), ('?wait=0', False)]:
                handler.path = f'/api/proxy/{vid}{query}'
                handler.do_GET()
                status.assert_called_with(vid, wait=expected)
