import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class ShortFolderScanPerformance(unittest.TestCase):
    def test_new_render_folder_scans_once_and_ignores_unrelated_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for n in range(100):
                (root / f'notes{n}.txt').touch()
            for name in ['002_old', '007_last', 'misc', '1000_ignored']:
                (root / name).mkdir()
            (root / '999_file').touch()
            original_iter = Path.iterdir
            original_is_dir = Path.is_dir
            scans, checked = [], []
            def iterdir(path):
                scans.append(path)
                return original_iter(path)
            def is_dir(path):
                if path.parent == root:
                    checked.append(path.name)
                return original_is_dir(path)
            with mock.patch.object(clipper, 'SHORT_DIR', root), \
                    mock.patch.object(Path, 'iterdir', iterdir), mock.patch.object(Path, 'is_dir', is_dir):
                result = clipper.short_folder('new')
            self.assertEqual(result, root / '008_new')
            self.assertEqual(scans, [root])
            self.assertEqual(sorted(checked), ['002_old', '007_last', '999_file'])

    def test_existing_project_uses_first_numbered_match_and_escapes_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ['009_a.b', '003_a.b', '001_axb']:
                (root / name).mkdir()
            with mock.patch.object(clipper, 'SHORT_DIR', root):
                self.assertEqual(clipper.short_folder('a.b'), root / '003_a.b')
                self.assertEqual(clipper.short_folder('missing'), root / '010_missing')
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(clipper, 'SHORT_DIR', Path(tmp) / 'shorts'):
                self.assertEqual(clipper.short_folder('first').name, '001_first')
