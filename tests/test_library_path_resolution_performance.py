import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class LibraryPathResolutionPerformance(unittest.TestCase):
    def test_scan_resolves_shared_roots_once_and_keeps_symlink_classification(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            library, broll, external = [root / n for n in ('clips', 'broll', 'outside')]
            for directory in (library, broll, external):
                directory.mkdir()
            for i in range(100):
                (library / f'{i}.mp4').touch()
            inside = broll / 'inside.mp4'
            outside = external / 'outside.mp4'
            inside.touch()
            outside.touch()
            alias = external / 'alias.mp4'
            alias.symlink_to(inside)
            original = Path.resolve
            calls = Counter()

            def resolve(path, *args, **kwargs):
                calls[path] += 1
                return original(path, *args, **kwargs)

            meta = {'duration': 10, 'width': 1920, 'height': 1080, 'video': 'h264', 'audio': 'aac'}
            with patch.object(clipper, 'LIBRARY_DIRS', [library, broll]), \
                 patch.object(clipper, 'BROLL_DIR', broll), \
                 patch.object(clipper, 'registry', {}), \
                 patch.object(clipper, 'extra_paths', return_value=[outside, alias]), \
                 patch.object(clipper, 'probe', return_value=meta), \
                 patch.object(Path, 'resolve', resolve):
                rows = {r['path']: r for r in clipper.scan_library()}
                self.assertEqual(rows[str(outside)]['remove'], 'unlist')
                self.assertFalse(rows[str(outside)]['broll'])
                self.assertEqual(rows[str(alias)]['remove'], 'trash')
                self.assertTrue(rows[str(alias)]['broll'])
                self.assertTrue(rows[str(inside)]['broll'])
                self.assertLessEqual(calls[broll], 2, 'shared roots must not resolve once per video')
                self.assertEqual(calls[library], 1)
                self.assertEqual(calls[alias], 1, 'classification must share resolved file parents')
                alias.unlink()
                alias.symlink_to(outside)
                rows = {r['path']: r for r in clipper.scan_library()}
                self.assertFalse(rows[str(alias)]['broll'])
                self.assertEqual(rows[str(alias)]['remove'], 'unlist')
