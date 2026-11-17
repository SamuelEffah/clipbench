"""Preview preparation should avoid encoding browser-compatible media."""
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import clipper


class ProxyPreparationTests(unittest.TestCase):
    def prepare(self, video='h264', audio='aac', results=(0,), pixel_format='yuv420p'):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        vid = 'e' * 12
        self.addCleanup(clipper.proxies.pop, vid, None)
        commands = []

        def launch(cmd, **kwargs):
            commands.append(cmd)
            Path(cmd[-1]).write_bytes(b'preview')
            return mock.Mock(stdout=io.StringIO('out_time_ms=1000000\n'),
                             stderr=io.StringIO('failed'), wait=mock.Mock(return_value=next(codes)))

        codes = iter(results)
        with mock.patch.object(clipper, 'PROXY_DIR', root), \
             mock.patch.object(clipper, 'probe', return_value={'duration': 2, 'video': video, 'audio': audio, 'pixel_format': pixel_format}), \
             mock.patch.object(clipper.subprocess, 'Popen', side_effect=launch):
            clipper.run_proxy(vid, root / 'source.mkv')
            self.assertEqual(clipper.proxies[vid]['state'], 'ready')
            self.assertTrue(clipper.proxy_path(vid).is_file())
            self.assertFalse((root / f'{vid}.part.mp4').exists())
        return commands

    def test_interrupted_progress_reader_stops_encoder_before_releasing_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            proc = mock.MagicMock(poll=mock.Mock(return_value=None))
            proc.stdout.__iter__ = mock.Mock(side_effect=OSError('read failed'))
            with mock.patch.object(clipper, 'PROXY_DIR', root), \
                 mock.patch.object(clipper, 'probe', return_value={'duration': 2}), \
                 mock.patch.object(clipper.subprocess, 'Popen', return_value=proc):
                with self.assertRaises(OSError):
                    clipper.run_proxy('interrupted-test', root / 'source.mkv')
            proc.terminate.assert_called_once()
            proc.wait.assert_called()
            proc.stdout.close.assert_called_once()

    def test_compatible_mkv_copies_streams_without_encoding(self):
        commands = self.prepare()
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertEqual(cmd[cmd.index('-c') + 1], 'copy')
        self.assertNotIn('-vf', cmd)
        self.assertIn('+faststart', cmd)

    def test_incompatible_codecs_keep_existing_transcode(self):
        for video, audio in [('vp9', 'opus'), ('h264', 'ac3')]:
            with self.subTest(video=video, audio=audio):
                commands = self.prepare(video, audio)
                self.assertEqual(len(commands), 1)
                self.assertIn('libx264', commands[0])
                self.assertIn('scale=-2:540', commands[0])

    def test_unusual_pixel_formats_keep_conversion(self):
        for pixel_format in (None, "yuv420p10le", "yuv444p"):
            with self.subTest(pixel_format=pixel_format):
                self.assertIn("libx264", self.prepare(pixel_format=pixel_format)[0])

    def test_copy_failure_falls_back_to_existing_transcode(self):
        commands = self.prepare(results=(1, 0))
        self.assertEqual(len(commands), 2)
        self.assertIn('copy', commands[0])
        self.assertIn('libx264', commands[1])

    def test_silent_and_mp3_sources_can_copy(self):
        for audio in (None, 'mp3'):
            with self.subTest(audio=audio):
                self.assertIn('copy', self.prepare(audio=audio)[0])


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class ProxyMediaTests(unittest.TestCase):
    def test_real_incompatible_video_is_encoded_for_browser_playback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source.avi'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=160x90:rate=10', '-t', '0.5',
                            '-c:v', 'mpeg4', str(source)], check=True, capture_output=True)
            vid = 'b' * 12
            self.addCleanup(clipper.proxies.pop, vid, None)
            with mock.patch.object(clipper, 'PROXY_DIR', root):
                clipper.run_proxy(vid, source)
                self.assertEqual(clipper.proxy_status(vid)['state'], 'ready')
                result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams',
                                         '-of', 'json', str(clipper.proxy_path(vid))],
                                        capture_output=True, text=True, check=True)
                stream = json.loads(result.stdout)['streams'][0]
                self.assertEqual(stream['codec_name'], 'h264')
                self.assertEqual(stream['height'], 540)
                self.assertEqual(stream['pix_fmt'], 'yuv420p')

    def test_real_remux_preserves_video_frames_and_audio(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / 'source.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=160x90:rate=10', '-f', 'lavfi', '-i',
                            'sine=frequency=440', '-t', '1', '-c:v', 'libx264',
                            '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)], check=True,
                           capture_output=True)
            vid = 'd' * 12
            self.addCleanup(clipper.proxies.pop, vid, None)
            with mock.patch.object(clipper, 'PROXY_DIR', root):
                clipper.run_proxy(vid, source)
                self.assertEqual(clipper.proxies[vid]['state'], 'ready')
                target = clipper.proxy_path(vid)
                def frames(path):
                    result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path),
                                             '-map', '0:v:0', '-f', 'hash', '-hash', 'sha256', '-'],
                                            capture_output=True, text=True, check=True)
                    return result.stdout
                self.assertEqual(frames(source), frames(target))
                info = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-show_streams',
                                                  '-of', 'json', str(target)],
                                                 capture_output=True, text=True, check=True).stdout)
                self.assertEqual([s['codec_name'] for s in info['streams']], ['h264', 'aac'])
