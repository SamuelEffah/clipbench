import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import make_short as ms


class SecondaryLaneEncodingLimit(unittest.TestCase):
    def test_split_render_limits_secondary_encoding_to_top_lane_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            src, cuts, out = [Path(folder) / n for n in ('source.mp4', 'cuts.txt', 'out.mp4')]
            src.touch()
            cuts.write_text('0:00 - 0:02\n@lane bottom\n0:00 - 0:08')
            args = ['make_short', str(src), '--cuts', str(cuts), '--card', '--layout', 'bare',
                    '--template', 'split', '-o', str(out)]
            with patch.object(sys, 'argv', args), \
                 patch.object(ms, 'build_montage', side_effect=[2., 8.]) as build, \
                 patch.object(ms, 'stack_lanes') as stack, \
                 patch.object(ms, 'card_geometry', return_value={'clip_w': 64, 'clip_h': 128}), \
                 patch.object(ms, 'render_card', return_value=(64, 128, 0, 0)), \
                 patch.object(ms.subprocess, 'run'), contextlib.redirect_stdout(io.StringIO()):
                ms.main()
            self.assertEqual(len(build.call_args_list), 2)
            self.assertIsNone(build.call_args_list[0].kwargs.get('output_limit'))
            self.assertEqual(build.call_args_list[1].kwargs.get('output_limit'), 2.,
                             'six seconds of the lower lane will never be displayed')
            self.assertEqual(stack.call_args.args[1], 2.)

    def test_limit_leaves_clip_effect_timing_unchanged_and_short_lanes_uncapped(self):
        options = [{**ms.DEFAULT_OPTIONS, 'fadeout': 1.}]
        with patch.object(ms, 'has_audio', return_value=False), patch.object(ms.subprocess, 'run') as run:
            length = ms.build_montage('source.mp4', [(0., 8., None)], 0, 'out.mp4', options,
                                      (64, 64), hold_last=True, output_limit=2.)
            cmd = run.call_args.args[0]
            self.assertEqual(length, 2.)
            self.assertIn('2.000', cmd)
            graph = cmd[cmd.index('-filter_complex') + 1]
            self.assertIn('fade=t=out:st=7.000:d=1.000', graph,
                          'the original fade must not move to the visible cutoff')
            ms.build_montage('source.mp4', [(0., 1., None)], 0, 'out.mp4', frame=(64, 64), output_limit=2.)
            cmd = run.call_args.args[0]
            self.assertEqual(cmd.count('-t'), 1, 'a short lane only needs its input duration')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_encoder_writes_only_visible_frames_and_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            src, full, limited = [str(Path(folder) / n) for n in ('source.mp4', 'full.mp4', 'limited.mp4')]
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=blue:s=64x64:r=30:d=8', '-c:v', 'libx264', src], check=True)
            for path, limit in [(full, None), (limited, 2.)]:
                ms.build_montage(src, [(0., 8., None)], 0, path, frame=(64, 64), hold_last=True, output_limit=limit)
            def frames(path):
                return int(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                            '-show_entries', 'stream=nb_frames', '-of', 'csv=p=0', path], text=True).strip())
            self.assertEqual(frames(full), 240)
            self.assertEqual(frames(limited), 60)
            self.assertAlmostEqual(ms.probe_duration(limited), 2., delta=.05)
