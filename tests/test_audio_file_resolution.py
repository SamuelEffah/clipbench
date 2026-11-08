import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class AudioFileResolutionTests(unittest.TestCase):
    def request(self, ident, headers=None):
        handler = object.__new__(clipper.Handler)
        handler.host_ok = lambda: True
        handler.path = '/audio-file/' + ident
        handler.headers = headers or {}
        handler.wfile = io.BytesIO()
        handler.sent = {}
        handler.send_response = lambda status: setattr(handler, 'status', status)
        handler.send_error = handler.send_response
        handler.send_header = lambda key, value: handler.sent.update({key: value})
        handler.end_headers = lambda: None
        handler.do_GET()
        return handler

    def test_known_audio_ranges_do_not_rescan_library_and_read_current_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            sound = Path(folder) / 'sound.mp3'
            sound.write_bytes(b'0123456789')
            with mock.patch.object(clipper, 'audio_registry', {'a' * 12: sound}), mock.patch.object(clipper, 'scan_audio') as scan:
                for _ in range(100):
                    response = self.request('a' * 12, {'Range': 'bytes=2-5'})
                    self.assertEqual(response.status, 206)
                    self.assertEqual(response.wfile.getvalue(), b'2345')
                scan.assert_not_called()
                sound.write_bytes(b'changed')
                self.assertEqual(self.request('a' * 12).wfile.getvalue(), b'changed')
                sound.unlink()
                self.assertEqual(self.request('a' * 12).status, 404)
                scan.assert_called_once()

    def test_unknown_sound_is_discovered_on_first_request(self):
        with tempfile.TemporaryDirectory() as folder:
            sound = Path(folder) / 'new.mp3'
            sound.write_bytes(b'new')
            with mock.patch.object(clipper, 'audio_registry', {}), mock.patch.object(clipper, 'scan_audio', side_effect=lambda: clipper.audio_registry.update({'b' * 12: sound})) as scan:
                self.assertEqual(self.request('b' * 12).wfile.getvalue(), b'new')
                self.assertEqual(self.request('b' * 12).wfile.getvalue(), b'new')
                scan.assert_called_once()
