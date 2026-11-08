import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from speech_cache import SpeechCache


class SpeechCacheLoadingTests(unittest.TestCase):
    def test_restart_loads_metadata_then_only_requested_words(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cache = SpeechCache(root, lambda *args: None)
            for i in range(100):
                cache._store(f'source-{i}', 0, 10, [[f'word-{i}', 1, 2]])
            # Build the metadata index once for legacy/new word files.
            SpeechCache(root, lambda *args: None)
            reads = []
            original = Path.read_text
            def read(path, *args, **kwargs):
                reads.append(path.name)
                return original(path, *args, **kwargs)
            with mock.patch.object(Path, 'read_text', read):
                again = SpeechCache(root, lambda *args: None)
                self.assertLessEqual(len(reads), 1, 'startup must not parse all 100 word files')
                reads.clear()
                self.assertEqual(again.find('source-42', 0, 10), [['word-42', 1, 2]])
                self.assertEqual(len(reads), 1)
                self.assertEqual(again.find('source-42', 0, 10), [['word-42', 1, 2]])
                self.assertEqual(len(reads), 1, 'repeated reads reuse loaded words')
                self.assertIsNone(again.find('unknown', 0, 10))
                self.assertEqual(len(reads), 1)

    def test_legacy_changed_and_removed_files_are_discovered(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            legacy = root / 'old.json'
            legacy.write_text(json.dumps({'src': 'old', 'a': 0, 'b': 5, 'words': [['old', 1, 2]]}))
            cache = SpeechCache(root, lambda *args: None)
            self.assertEqual(cache.find('old', 0, 5), [['old', 1, 2]])
            legacy.write_text(json.dumps({'src': 'old', 'a': 0, 'b': 6, 'words': [['changed', 1, 3]]}))
            (root / 'new.json').write_text(json.dumps({'src': 'new', 'a': 0, 'b': 5, 'words': []}))
            again = SpeechCache(root, lambda *args: None)
            self.assertEqual(again.find('old', 0, 6), [['changed', 1, 3]])
            self.assertEqual(again.find('new', 0, 5), [])
            legacy.unlink()
            self.assertIsNone(SpeechCache(root, lambda *args: None).find('old', 0, 5))

    def test_corrupt_metadata_is_rebuilt_without_losing_saved_words(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cache = SpeechCache(root, lambda *args: None)
            cache._store('source', 0, 10, [['word', 1, 2]])
            SpeechCache(root, lambda *args: None)
            index = root / '.index.json'
            data = json.loads(index.read_text())
            next(iter(data['files'].values()))['a'] = 'invalid'
            index.write_text(json.dumps(data))
            again = SpeechCache(root, lambda *args: None)
            self.assertEqual(again.find('source', 0, 10), [['word', 1, 2]])
