import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class SceneDataCacheTests(unittest.TestCase):
    def test_reuse_replacement_deletion_and_bound(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(clipper, '_scene_data', clipper.OrderedDict()):
            path = Path(folder) / 'scenes.json'
            path.write_text('[1,2]')
            original = Path.read_text
            reads = []
            def read(p, *args, **kwargs):
                if p == path:
                    reads.append(p)
                return original(p, *args, **kwargs)
            with patch.object(Path, 'read_text', read):
                for _ in range(100):
                    self.assertEqual(clipper.read_scenes(path), [1, 2])
                self.assertEqual(len(reads), 1)
                clipper.read_scenes(path).append(99)
                self.assertEqual(clipper.read_scenes(path), [1, 2])
                path.write_text('[3,4]')
                self.assertEqual(clipper.read_scenes(path), [3, 4])
                path.unlink()
                with self.assertRaises(OSError):
                    clipper.read_scenes(path)
                path.write_text('invalid')
                with self.assertRaises(ValueError):
                    clipper.read_scenes(path)
                path.write_text('[5]')
                self.assertEqual(clipper.read_scenes(path), [5])
            for i in range(clipper.SCENE_DATA_LIMIT + 5):
                other = Path(folder) / str(i)
                other.write_text('[]')
                clipper.read_scenes(other)
            self.assertEqual(len(clipper._scene_data), clipper.SCENE_DATA_LIMIT)
