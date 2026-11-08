import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class AudioWaveLookupPerformance(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.src = self.root / 'sound.wav'
        self.src.write_bytes(b'audio')
        patch = mock.patch.object(clipper, 'audio_registry', {'known': self.src})
        patch.start()
        self.addCleanup(patch.stop)

    def test_registered_wave_requests_do_not_scan_audio_library(self):
        wave = {'per_sec': 50, 'peaks': [1, 2]}
        with mock.patch.object(clipper, 'scan_audio') as scan, mock.patch.object(clipper, '_cached_wave', return_value=wave) as load:
            for _ in range(100):
                self.assertEqual(clipper.load_audio_wave('known'), wave)
            scan.assert_not_called()
            self.assertEqual(load.call_count, 100)
            load.assert_called_with(self.src, clipper.PROXY_DIR / 'known.audiowave.json', 50)

    def test_unknown_sound_is_discovered_before_loading(self):
        def scan():
            clipper.audio_registry['new'] = self.src
        with mock.patch.object(clipper, 'scan_audio', side_effect=scan) as discover, mock.patch.object(clipper, '_cached_wave', return_value={}) as load:
            self.assertEqual(clipper.load_audio_wave('new'), {})
            discover.assert_called_once()
            load.assert_called_once()

    def test_missing_files_and_unknown_ids_do_not_decode(self):
        self.src.unlink()
        with mock.patch.object(clipper, 'scan_audio') as scan, mock.patch.object(clipper, '_cached_wave') as load:
            self.assertIsNone(clipper.load_audio_wave('known'))
            self.assertIsNone(clipper.load_audio_wave('missing'))
            self.assertEqual(scan.call_count, 2)
            load.assert_not_called()

    def test_replaced_source_still_goes_through_versioned_wave_cache(self):
        with mock.patch.object(clipper, 'scan_audio') as scan, mock.patch.object(clipper, '_cached_wave', side_effect=[{'peaks': [1]}, {'peaks': [2]}]):
            self.assertEqual(clipper.load_audio_wave('known'), {'peaks': [1]})
            self.src.write_bytes(b'replaced audio')
            self.assertEqual(clipper.load_audio_wave('known'), {'peaks': [2]})
            scan.assert_not_called()
