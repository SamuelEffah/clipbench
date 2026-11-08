import array
import io
import subprocess
import sys
import tempfile
import tracemalloc
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import clipper


def expected_wave(pcm, per_sec):
    samples = array.array("h")
    samples.frombytes(pcm[:len(pcm) // 2 * 2])
    step = clipper.WAVE_RATE // per_sec
    raw = [max(map(abs, samples[i:i + step])) for i in range(0, len(samples), step)]
    if not raw:
        return {"per_sec": per_sec, "peaks": []}
    ceiling = sorted(raw)[int(len(raw) * 0.99)] or 1
    return {"per_sec": per_sec, "peaks": [min(255, round(v / ceiling * 255)) for v in raw]}


class WaveStreaming(unittest.TestCase):
    def run_wave(self, pcm, per_sec=20, returncode=0, max_read=None):
        class ShortReads(io.BytesIO):
            def read(self, size):
                return super().read(min(size, max_read) if max_read else size)

        proc = mock.MagicMock()
        proc.__enter__.return_value = proc
        proc.stdout = ShortReads(pcm)
        proc.wait.return_value = returncode
        with mock.patch.object(clipper.subprocess, "Popen", return_value=proc), mock.patch.object(clipper.subprocess, "run") as run:
            result = clipper.compute_wave("fixture", per_sec)
        run.assert_not_called()
        return result

    def test_streamed_wave_matches_previous_buckets_and_normalization(self):
        pcm = array.array("h", [-32768, -300, 0, 100, 12000, 32767] * 10003).tobytes()
        for per_sec in (20, 50):
            with self.subTest(per_sec=per_sec):
                self.assertEqual(self.run_wave(pcm, per_sec), expected_wave(pcm, per_sec))

    def test_empty_silent_and_truncated_samples(self):
        for pcm in (b"", b"\xff", b"\x00" * 1801, b"\xff\x7f\xff"):
            self.assertEqual(self.run_wave(pcm), expected_wave(pcm, 20))

    def test_failed_decoder_discards_partial_audio(self):
        self.assertEqual(self.run_wave(b"\xff\x7f" * 1000, returncode=1), {"per_sec": 20, "peaks": []})

    def test_short_pipe_reads_preserve_buckets_and_split_samples(self):
        pcm = array.array("h", [-32768, -200, 0, 123, 32767] * 2003).tobytes()
        for per_sec in (20, 50):
            self.assertEqual(self.run_wave(pcm, per_sec, max_read=37), expected_wave(pcm, per_sec))

    def test_long_audio_does_not_allocate_a_second_full_pcm_buffer(self):
        pcm = b"\x10\x00" * (clipper.WAVE_RATE * 120)
        tracemalloc.start()
        try:
            result = self.run_wave(pcm)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(len(result["peaks"]), 2400)
        self.assertLess(peak, 1024 * 1024)

    def test_actual_ffmpeg_output_matches_previous_waveform(self):
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder) / "tone.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.273", str(src)], check=True)
            pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-map", "0:a:0", "-ac", "1", "-ar", str(clipper.WAVE_RATE), "-f", "s16le", "-"], capture_output=True, check=True).stdout
            for per_sec in (20, 50):
                self.assertEqual(clipper.compute_wave(src, per_sec), expected_wave(pcm, per_sec))
