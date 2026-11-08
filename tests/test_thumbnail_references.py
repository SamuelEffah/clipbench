import base64
from concurrent.futures import ThreadPoolExecutor
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper
from thumbnails import ThumbnailStore
from store import Store

IMAGE = b'\xff\xd8\xff' + b'image data' * 1000
URI = 'data:image/jpeg;base64,' + base64.b64encode(IMAGE).decode()


class ThumbnailReferenceTests(unittest.TestCase):
    def test_project_save_keeps_one_image_file_and_small_references(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project = {'name': 'demo', 'clips': [{'src': 'source', 'thumb': URI} for _ in range(100)], 'bank': [{'thumb': URI}]}
            handler = object.__new__(clipper.Handler)
            handler.host_ok = handler.origin_ok = lambda: True
            handler.path = '/api/project/demo'
            handler.read_json = lambda: project
            handler.send_json = mock.Mock()
            store = Store(root / 'data.db')
            with mock.patch.object(clipper, 'store', store), mock.patch.object(clipper, 'CLIP_THUMB_DIR', root / 'thumbs', create=True):
                handler.do_PUT()
            saved = store.get_project('demo')
            self.assertLess(len(json.dumps(saved)), len(json.dumps(project)) // 20)
            files = list((root / 'thumbs').iterdir())
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].read_bytes(), IMAGE)
            self.assertTrue(saved['clips'][0]['thumb'].startswith('/clip-thumb/'))
            self.assertEqual(project['clips'][0]['thumb'], URI, 'saving must not mutate caller data')
            self.assertEqual(len(handler.send_json.call_args.args[0]['thumbs']), 101)

    def test_existing_urls_and_invalid_legacy_images_remain_compatible(self):
        with tempfile.TemporaryDirectory() as folder:
            data = [{'thumb': '/video-thumb/abc.jpg'}, {'thumb': 'data:image/jpeg;base64,invalid'}, {'src': 'source'}]
            converted, refs = ThumbnailStore(folder).externalize(data)
            self.assertEqual(converted, data)
            self.assertEqual(refs, [])

    def test_shared_saved_clip_stays_shared_when_its_thumbnail_is_externalized(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'data.db')
            old = {'src': 'source', 'thumb': URI}
            store.replace_favorites([old])
            converted, _ = ThumbnailStore(Path(folder) / 'thumbs').externalize([old])
            store.replace_favorites_for('demo', converted)
            self.assertEqual(store.list_favorites('other'), converted)

    def test_concurrent_thumbnail_writes_publish_one_complete_image(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ThumbnailStore(folder)
            with ThreadPoolExecutor(max_workers=8) as pool:
                rows = list(pool.map(lambda _: store.externalize([{'thumb': URI}])[0], range(8)))
            self.assertTrue(all(row == rows[0] for row in rows))
            files = list(Path(folder).iterdir())
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].read_bytes(), IMAGE)

    def test_thumbnail_reference_route_serves_the_saved_image(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            converted, _ = ThumbnailStore(root).externalize([{'thumb': URI}])
            handler = object.__new__(clipper.Handler)
            handler.host_ok = lambda: True
            handler.path = converted[0]['thumb']
            handler.serve_file = mock.Mock()
            with mock.patch.object(clipper, 'CLIP_THUMB_DIR', root):
                handler.do_GET()
            handler.serve_file.assert_called_once_with(next(root.iterdir()), 'image/jpeg')

    def test_embedded_fallback_still_saves_when_image_directory_is_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'data.db')
            handler = object.__new__(clipper.Handler)
            handler.host_ok = handler.origin_ok = lambda: True
            handler.path = '/api/project/demo'
            project = {'clips': [{'thumb': URI}]}
            handler.read_json = lambda: project
            handler.send_json = mock.Mock()
            with mock.patch.object(clipper, 'store', store), \
                 mock.patch.object(clipper.ThumbnailStore, 'externalize', side_effect=PermissionError('read only')):
                handler.do_PUT()
            self.assertEqual(store.get_project('demo'), project)
            handler.send_json.assert_called_once_with({'ok': True})
