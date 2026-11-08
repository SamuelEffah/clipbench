import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class FileCacheValidationTests(unittest.TestCase):
    def request(self, path, headers=None):
        handler = object.__new__(clipper.Handler)
        handler.headers = headers or {}
        handler.wfile = io.BytesIO()
        handler.status = None
        handler.sent = {}
        handler.send_response = lambda code: setattr(handler, 'status', code)
        handler.send_header = lambda key, value: handler.sent.update({key: value})
        handler.end_headers = lambda: None
        handler.send_error = handler.send_response
        handler.serve_file(path, 'image/jpeg')
        return handler

    def test_unchanged_asset_returns_304_without_opening_or_sending_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'thumb.jpg'
            path.write_bytes(b'jpeg' * 10000)
            first = self.request(path)
            self.assertEqual(first.status, 200)
            etag = first.sent.get('ETag')
            self.assertIsNotNone(etag, 'assets need a validator to avoid resending unchanged bytes')
            with mock.patch('builtins.open', side_effect=AssertionError('304 must not open the body')):
                cached = self.request(path, {'If-None-Match': etag})
            self.assertEqual(cached.status, 304)
            self.assertEqual(cached.wfile.getvalue(), b'')
            path.write_bytes(b'new image')
            changed = self.request(path, {'If-None-Match': etag})
            self.assertEqual(changed.status, 200)
            self.assertEqual(changed.wfile.getvalue(), b'new image')
            self.assertNotEqual(changed.sent['ETag'], etag)

    def test_range_requests_keep_partial_content_even_with_cache_validator(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'video.mp4'
            path.write_bytes(b'0123456789')
            first = self.request(path)
            partial = self.request(path, {'Range': 'bytes=2-5', 'If-None-Match': first.sent.get('ETag', '')})
            self.assertEqual(partial.status, 206)
            self.assertEqual(partial.wfile.getvalue(), b'2345')
            self.assertEqual(partial.sent['Content-Range'], 'bytes 2-5/10')

    def test_stale_if_range_returns_full_updated_resource(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'video.mp4'
            path.write_bytes(b'0123456789')
            reply = self.request(path, {'Range': 'bytes=2-5', 'If-Range': '"old"'})
            self.assertEqual(reply.status, 200)
            self.assertEqual(reply.wfile.getvalue(), b'0123456789')
