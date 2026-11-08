import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import shorts


class ShortListingStatPerformance(unittest.TestCase):
    def test_each_rendered_video_uses_one_metadata_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(100):
                folder = root / f'{i:03d}_short{i}'
                folder.mkdir()
                (folder / 'video.mp4').write_bytes(b'video')
            missing = root / '100_missing'
            missing.mkdir()
            directory = root / '101_directory'
            directory.mkdir()
            (directory / 'video.mp4').mkdir()
            calls = []
            original = Path.stat
            def stat(path, *args, **kwargs):
                if path.name == 'video.mp4':
                    calls.append(path)
                return original(path, *args, **kwargs)
            with mock.patch.object(Path, 'stat', stat):
                rows = shorts.list_shorts(root, ['short0'], lambda name: {'state': 'none'}, lambda video: 12.)
            self.assertEqual(len(rows), 100)
            for row in rows:
                self.assertEqual(row['size'], 5)
                self.assertEqual(row['duration'], 12.)
                self.assertEqual(row['has_project'], row['name'] == 'short0')
                self.assertEqual(row['upload'], {'state': 'none'})
                self.assertEqual(calls.count(root / row['folder'] / 'video.mp4'), 1)
            self.assertEqual(len(calls), 102)
