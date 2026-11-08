#!/usr/bin/env python3
"""Compare source-preview preparation paths on this machine; touches temporary files only."""
import argparse
import json
import re
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path


def run(command):
    return subprocess.run(command, capture_output=True, text=True, check=True)


def benchmark(seconds, runs):
    with tempfile.TemporaryDirectory(prefix='clipbench-preview-bench-') as folder:
        root = Path(folder)
        source = root / 'source.mkv'
        run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=30',
             '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', str(seconds), '-c:v', 'libx264',
             '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)])
        encode = ['-vf', 'scale=-2:540', '-pix_fmt', 'yuv420p', '-g', '15', '-c:a', 'aac', '-b:a', '96k']
        variants = {
            'copy': ['-c', 'copy'],
            'software': encode + ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26'],
            'hardware': encode + ['-c:v', 'h264_videotoolbox', '-allow_sw', '0', '-b:v', '3M',
                                    '-realtime', '1', '-prio_speed', '1'],
        }
        results = {'source_seconds': seconds, 'runs': runs, 'paths': {}}
        for name, options in variants.items():
            target = root / f'{name}.mp4'
            samples = []
            try:
                for _ in range(runs):
                    started = time.perf_counter()
                    run(['ffmpeg', '-y', '-v', 'error', '-i', str(source), '-map', '0:v:0',
                         '-map', '0:a:0?', '-sn', '-dn', '-map_chapters', '-1'] + options
                        + ['-movflags', '+faststart', str(target)])
                    samples.append(time.perf_counter() - started)
                # Compare encoded video with the same downscaled source. SSIM=1 is identical.
                graph = '[1:v]scale=-2:540[ref];[0:v][ref]ssim' if name != 'copy' else '[0:v][1:v]ssim'
                quality = run(['ffmpeg', '-v', 'info', '-i', str(target), '-i', str(source),
                               '-lavfi', graph, '-an', '-f', 'null', '-'])
                match = re.search(r'All:([0-9.]+)', quality.stderr)
                results['paths'][name] = {
                    'seconds': [round(t, 4) for t in samples],
                    'median_seconds': round(statistics.median(samples), 4),
                    'bytes': target.stat().st_size,
                    'ssim': float(match[1]) if match else None,
                }
            except subprocess.CalledProcessError as error:
                results['paths'][name] = {'unavailable': error.stderr.strip()[-500:]}
        return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=12)
    parser.add_argument('--runs', type=int, default=3)
    args = parser.parse_args()
    if args.seconds <= 0 or args.runs < 1:
        parser.error('--seconds and --runs must be positive')
    if not shutil.which('ffmpeg'):
        parser.error('ffmpeg is required')
    print(json.dumps(benchmark(args.seconds, args.runs), indent=2))


if __name__ == '__main__':
    main()
