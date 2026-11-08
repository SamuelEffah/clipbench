import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import shorts


class ShortThumbnailConcurrency(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        (self.folder / 'video.mp4').write_bytes(b'video')

    def test_simultaneous_cover_requests_encode_once(self):
        gate = threading.Barrier(8)
        calls = []
        def make(src, dest):
            calls.append(src)
            time.sleep(.05)
            dest.write_bytes(b'cover')
            return True
        def request(_):
            gate.wait(timeout=5)
            return shorts.thumbnail(self.folder, make)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(request, range(8)))
        self.assertEqual(len(calls), 1)
        self.assertEqual(results, [self.folder / 'thumb.jpg'] * 8)
        self.assertEqual(results[0].read_bytes(), b'cover')
        self.assertEqual(shorts.thumbnail(self.folder, make), results[0])
        self.assertEqual(len(calls), 1)

    def test_different_covers_encode_in_parallel(self):
        other = self.folder / 'other'
        other.mkdir()
        (other / 'video.mp4').write_bytes(b'video')
        gate = threading.Barrier(2)
        def make(src, dest):
            gate.wait(timeout=5)
            dest.write_bytes(src.parent.name.encode())
            return True
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(shorts.thumbnail, folder, make) for folder in (self.folder, other)]
            results = [job.result(timeout=5) for job in jobs]
        self.assertNotEqual(results[0], results[1])
        self.assertTrue(all(path.is_file() for path in results))

    def test_failed_cover_can_be_retried(self):
        self.assertIsNone(shorts.thumbnail(self.folder, lambda *_: False))
        def fail(*_):
            raise OSError('encoder failed')
        with self.assertRaisesRegex(OSError, 'encoder failed'):
            shorts.thumbnail(self.folder, fail)
        def make(src, dest):
            dest.write_bytes(b'retried')
            return True
        self.assertEqual(shorts.thumbnail(self.folder, make).read_bytes(), b'retried')
