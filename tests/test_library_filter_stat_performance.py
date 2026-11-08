import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class LibraryFilterStatPerformance(unittest.TestCase):
    def test_ignored_entries_are_filtered_before_file_metadata_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for n in range(100):
                (root / f'notes{n}.txt').touch()
                (root / f'.hidden{n}.mp4').touch()
            video = root / 'episode.MP4'
            video.touch()
            (root / 'directory.mp4').mkdir()
            original = Path.is_file
            checked = []
            def is_file(path):
                if path.parent == root:
                    checked.append(path.name)
                return original(path)
            meta = {'duration': 60., 'width': 1920, 'height': 1080, 'video': 'h264', 'audio': 'aac'}
            with mock.patch.object(clipper, 'LIBRARY_DIRS', [root]), \
                    mock.patch.object(clipper, 'extra_paths', return_value=[]), \
                    mock.patch.object(clipper, 'registry', {}), \
                    mock.patch.object(clipper, 'probe', return_value=meta), \
                    mock.patch.object(Path, 'is_file', is_file):
                rows = clipper.scan_library()
            self.assertEqual([row['path'] for row in rows], [str(video)])
            self.assertTrue(rows[0]['direct'])
            self.assertEqual(sorted(checked), ['directory.mp4', 'episode.MP4'])

    def test_audio_library_filters_ignored_entries_before_metadata_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for n in range(100):
                (root / f'notes{n}.txt').touch()
                (root / f'.hidden{n}.mp3').touch()
            song = root / 'song.MP3'
            effect = root / 'effect.wav'
            song.touch()
            effect.touch()
            (root / 'directory.mp3').mkdir()
            checked = []
            original = Path.is_file
            def is_file(path):
                if path.parent == root:
                    checked.append(path.name)
                return original(path)
            def duration(path):
                return 60.123 if path == song else 2.456
            with mock.patch.object(clipper, 'AUDIO_DIRS', [root]), \
                    mock.patch.object(clipper, 'audio_registry', {}), \
                    mock.patch.object(clipper, 'audio_duration', side_effect=duration), \
                    mock.patch.object(Path, 'is_file', is_file):
                rows = clipper.scan_audio()
            self.assertEqual([(row['name'], row['duration'], row['kind']) for row in rows],
                             [('effect', 2.46, 'sfx'), ('song', 60.12, 'song')])
            self.assertEqual(sorted(checked), ['directory.mp3', 'effect.wav', 'song.MP3'])
