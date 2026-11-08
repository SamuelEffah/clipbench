import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import clipper


class MetadataProbes(unittest.TestCase):
    def test_concurrent_requests_share_one_probe(self):
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder) / "video.mp4"
            src.write_bytes(b"video")
            gate = threading.Barrier(8)

            def expensive_probe(path):
                time.sleep(0.05)
                return {"duration": 60}

            def request(_):
                gate.wait(timeout=5)
                return clipper.probe(src)

            with mock.patch.object(clipper, "_probes", {}), mock.patch.object(clipper, "_probe", side_effect=expensive_probe) as probe:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(request, range(8)))
                self.assertEqual(results, [{"duration": 60}] * 8)
                self.assertEqual(probe.call_count, 1)
                src.write_bytes(b"changed video")
                self.assertEqual(clipper.probe(src), {"duration": 60})
                self.assertEqual(probe.call_count, 2)

    def test_failed_probe_can_be_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder) / "video.mp4"
            src.touch()
            with mock.patch.object(clipper, "_probes", {}), mock.patch.object(clipper, "_probe", side_effect=[RuntimeError("failed"), {"duration": 60}]) as probe:
                with self.assertRaisesRegex(RuntimeError, "failed"):
                    clipper.probe(src)
                self.assertEqual(clipper.probe(src), {"duration": 60})
                self.assertEqual(probe.call_count, 2)

    def test_different_videos_can_probe_in_parallel(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / name for name in ("one.mp4", "two.mp4")]
            for path in paths:
                path.touch()
            gate = threading.Barrier(2)

            def probe(path):
                gate.wait(timeout=5)
                return {"duration": 60}

            with mock.patch.object(clipper, "_probes", {}), mock.patch.object(clipper, "_probe", side_effect=probe):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    self.assertEqual(list(pool.map(clipper.probe, paths)), [{"duration": 60}] * 2)


class LibraryScan(unittest.TestCase):
    def test_imported_paths_are_read_once_per_scan(self):
        with mock.patch.object(clipper, "LIBRARY_DIRS", []), mock.patch.object(clipper, "extra_paths", return_value=[]) as paths:
            self.assertEqual(clipper.scan_library(), [])
            paths.assert_called_once_with()
