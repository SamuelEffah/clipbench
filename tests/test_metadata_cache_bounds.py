import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class MetadataCacheBoundsTests(unittest.TestCase):
    def test_probe_and_duration_caches_drop_old_versions_and_bound_long_sessions(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(clipper, '_probes', {}), \
             mock.patch.object(clipper, 'durations', {}), \
             mock.patch.object(clipper, '_probe', return_value={'duration': 10}) as probe:
            root = Path(folder)
            path = root / 'changing.mp4'
            for i in range(20):
                path.write_bytes(b'x' * (i + 1))
                self.assertEqual(clipper.probe(path)['duration'], 10)
                self.assertEqual(clipper.short_duration(path), 10)
            self.assertEqual(len(clipper._probes), 1, 'old source versions should not accumulate')
            self.assertEqual(len(clipper.durations), 1)
            for i in range(clipper.METADATA_CACHE_LIMIT + 50):
                path = root / f'{i}.mp4'
                path.write_bytes(b'x')
                clipper.probe(path)
                clipper.short_duration(path)
            self.assertLessEqual(len(clipper._probes), clipper.METADATA_CACHE_LIMIT)
            self.assertLessEqual(len(clipper.durations), clipper.METADATA_CACHE_LIMIT)
            before = probe.call_count
            clipper.probe(path)
            clipper.short_duration(path)
            self.assertEqual(probe.call_count, before, 'recent entries should still be reused')

    def test_a_modest_library_can_be_scanned_again_without_cache_thrashing(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(clipper, '_probes', {}), \
             mock.patch.object(clipper, '_probe', return_value={'duration': 10}) as probe:
            files = [Path(folder) / f'{i}.mp4' for i in range(200)]
            for path in files:
                path.write_bytes(b'source')
            for _ in range(2):
                for path in files:
                    clipper.probe(path)
            self.assertEqual(probe.call_count, 200, 'a second 200-source scan should reuse metadata')
