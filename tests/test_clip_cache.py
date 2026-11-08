"""Rendered clips are kept between renders, so a Short only redoes the clips that changed."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import clip_cache  # noqa: E402
import make_short as ms  # noqa: E402

O = ms.DEFAULT_OPTIONS


class Keys(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = Path(self.tmp) / "a.mp4"
        self.src.write_bytes(b"video")
        self.inputs = ["-ss", "1.000", "-t", "2.000", "-i", str(self.src)]

    def test_the_same_clip_has_the_same_key(self):
        a = clip_cache.clip_key(self.inputs, ["[0:v]null[v0]"], ["-c:v", "x"])
        self.assertEqual(a, clip_cache.clip_key(list(self.inputs), ["[0:v]null[v0]"], ["-c:v", "x"]))

    def test_a_changed_range_filter_or_encoder_changes_the_key(self):
        a = clip_cache.clip_key(self.inputs, ["[0:v]null[v0]"], ["-c:v", "x"])
        self.assertNotEqual(a, clip_cache.clip_key(["-ss", "1.500", *self.inputs[2:]], ["[0:v]null[v0]"], ["-c:v", "x"]))
        self.assertNotEqual(a, clip_cache.clip_key(self.inputs, ["[0:v]hflip[v0]"], ["-c:v", "x"]))
        self.assertNotEqual(a, clip_cache.clip_key(self.inputs, ["[0:v]null[v0]"], ["-c:v", "y"]))
        self.assertNotEqual(a, clip_cache.clip_key(self.inputs, ["[0:v]null[v0]"], ["-c:v", "x"], 31))

    def test_frames_round_to_the_nearest_whole_frame_and_never_none(self):
        self.assertEqual([clip_cache.frame_count(s) for s in (3.4, 3.41, 3.42, 0.01)], [102, 102, 103, 1])

    def test_a_rewritten_source_file_changes_the_key(self):
        a = clip_cache.clip_key(self.inputs, [], [])
        self.src.write_bytes(b"other video")
        os.utime(self.src, ns=(1, 1))
        self.assertNotEqual(a, clip_cache.clip_key(self.inputs, [], []))


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cache = clip_cache.ClipCache(self.tmp)
        self.spec = (["-i", "a.mp4"], ["f"], ["c"], 30)

    def render_writing(self, data, made=None):
        def render(inputs, filters, codec, frames, dest):
            if made is not None:
                made.append(dest)
            Path(dest).write_bytes(data)
        return render

    def test_a_clip_is_rendered_once_and_then_reused(self):
        made = []
        first = self.cache.clips([self.spec], self.render_writing(b"x", made))
        second = self.cache.clips([self.spec], self.render_writing(b"x", made))
        self.assertEqual(first, second)
        self.assertEqual(len(made), 1)
        self.assertTrue(Path(first[0]).is_file())
        self.assertEqual((self.cache.hits, self.cache.misses), (1, 1))

    def test_files_come_back_in_clip_order_whatever_was_kept(self):
        specs = [(["-i", f"{n}.mp4"], [], [], 30) for n in range(5)]
        self.cache.clips(specs[1:3], self.render_writing(b"x"))
        files = self.cache.clips(specs, self.render_writing(b"x"))
        self.assertEqual([clip_cache.clip_key(*s) for s in specs], [Path(f).stem[len("clip-"):] for f in files])
        self.assertEqual((self.cache.hits, self.cache.misses), (2, 5))

    def test_a_failed_render_leaves_nothing_behind(self):
        def render(inputs, filters, codec, frames, dest):
            Path(dest).write_bytes(b"half")
            raise subprocess.CalledProcessError(1, "ffmpeg")

        with self.assertRaises(subprocess.CalledProcessError):
            self.cache.clips([self.spec], render)
        self.assertEqual(list(Path(self.tmp).glob("*" + clip_cache.SUFFIX)), [])

    def test_an_empty_kept_file_is_rendered_again(self):
        [path] = self.cache.clips([self.spec], self.render_writing(b""))
        self.cache.clips([self.spec], self.render_writing(b"ok"))
        self.assertEqual(Path(path).read_bytes(), b"ok")

    def test_pruning_drops_the_least_recently_used_clips_first(self):
        for n in range(4):
            [path] = self.cache.clips([(["-i", f"{n}.mp4"], [], [], 30)], self.render_writing(b"x" * 100))
            os.utime(path, ns=(n * 10 ** 9, n * 10 ** 9))
        (Path(self.tmp) / f"part-stray{clip_cache.SUFFIX}").write_bytes(b"junk")
        self.cache.limit = 250
        self.cache.prune()
        left = sorted(p.name for p in Path(self.tmp).glob("*" + clip_cache.SUFFIX))
        self.assertEqual(len(left), 2)
        self.assertNotIn(f"part-stray{clip_cache.SUFFIX}", left)
        self.assertIsNotNone(self.cache.get(clip_cache.clip_key(["-i", "3.mp4"], [], [], 30)))

    def test_loudness_is_measured_once_per_range(self):
        measure = mock.Mock(return_value=-20.5)
        self.assertEqual(self.cache.loudness("a.mp4", 1.0, 2.0, 0, measure), -20.5)
        self.assertEqual(self.cache.loudness("a.mp4", 1.0, 2.0, 0, measure), -20.5)
        self.cache.loudness("a.mp4", 1.0, 2.5, 0, measure)
        self.assertEqual(measure.call_count, 2)
        self.assertEqual(clip_cache.ClipCache(self.tmp).loudness("a.mp4", 1.0, 2.0, 0, measure), -20.5)
        self.assertEqual(measure.call_count, 2)

    def test_a_silent_measurement_is_kept_too(self):
        measure = mock.Mock(return_value=None)
        self.cache.loudness("a.mp4", 0.0, 1.0, 0, measure)
        self.cache.loudness("a.mp4", 0.0, 1.0, 0, measure)
        measure.assert_called_once()

    def test_a_broken_loudness_file_is_ignored(self):
        (Path(self.tmp) / clip_cache.LOUDNESS_FILE).write_text("{not json")
        self.assertEqual(self.cache.loudness("a.mp4", 0.0, 1.0, 0, lambda *a: -18.0), -18.0)
        self.assertEqual(list(json.loads((Path(self.tmp) / clip_cache.LOUDNESS_FILE).read_text()).values()), [-18.0])

    def test_a_list_names_every_file_in_order_with_quotes_escaped(self):
        odd = Path(self.tmp) / "it's.mov"
        text = Path(clip_cache.write_list([odd, Path(self.tmp) / "b.mov"], Path(self.tmp) / "list.txt")).read_text()
        lines = text.splitlines()
        self.assertEqual(lines[0], "ffconcat version 1.0")
        self.assertEqual(lines[1], "file '" + str(odd.resolve()).replace("'", "'\\''") + "'")
        self.assertTrue(lines[2].endswith("b.mov'"))
        self.assertEqual(clip_cache.list_input("x.txt")[-2:], ["-i", "x.txt"])


class MontageWithCache(unittest.TestCase):
    """build_montage with a cache renders each clip to its own file, then joins the files."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cache = clip_cache.ClipCache(Path(self.tmp) / "cache")
        self.cuts = [(0.0, 2.0, "a.mp4"), (5.0, 7.0, "a.mp4"), (9.0, 10.0, "a.mp4")]

    def build(self, options, **kwargs):
        calls = []

        def run(cmd, *a, **k):
            calls.append(cmd)
            if cmd[-1].endswith((".mp4", clip_cache.SUFFIX)) and "-filter_complex" in cmd:
                Path(cmd[-1]).write_bytes(b"x")

        with mock.patch.object(ms.subprocess, "run", side_effect=run), mock.patch.object(clip_cache.subprocess, "run", side_effect=run), \
                mock.patch.object(ms, "has_audio", return_value=True), mock.patch.object(ms, "probe_size", return_value=(1920, 1080)), \
                mock.patch.object(ms, "_hardware_h264", True), mock.patch.object(clip_cache, "PARALLEL", 1):
            length = ms.build_montage("a.mp4", self.cuts, 0, str(Path(self.tmp) / "out.mp4"), options, (1080, 1920), cache=self.cache, **kwargs)
        return length, [c for c in calls if "-filter_complex" in c]

    def test_the_first_render_makes_every_clip_then_joins_them(self):
        options = [dict(O) for _ in self.cuts]
        length, encodes = self.build(options)
        self.assertEqual(length, 5.0)
        self.assertEqual(len(encodes), 4)
        for cmd, frames in zip(encodes[:3], (60, 60, 30)):
            self.assertEqual(cmd[cmd.index("-map") + 1], "[vf]")
            self.assertEqual(cmd[cmd.index("-frames:v") + 1], str(frames))
        join = encodes[-1]
        self.assertEqual(join.count("-i"), 3)
        self.assertTrue(all(Path(cmd[-1]).parent == self.cache.dir for cmd in encodes[:3]))
        graph = join[join.index("-filter_complex") + 1]
        self.assertIn("concat=n=3:v=1:a=1[v][a]", graph)

    def test_the_second_render_only_joins(self):
        options = [dict(O) for _ in self.cuts]
        self.build(options)
        _, encodes = self.build(options)
        self.assertEqual(len(encodes), 1)

    def test_changing_one_clip_renders_only_that_clip(self):
        options = [dict(O) for _ in self.cuts]
        self.build(options)
        changed = [dict(O), {**O, "zoom": 1.3}, dict(O)]
        _, encodes = self.build(changed)
        self.assertEqual(len(encodes), 2)
        self.assertIn("crop=iw/1.3000", encodes[0][encodes[0].index("-filter_complex") + 1])

    def test_the_clip_chain_matches_the_single_graph(self):
        """What a cached clip is rendered with is exactly the chain the one-pass graph gives that clip."""
        options = [{**O, "fit": "fill", "effect": "zoom_in", "fadein": 0.3, "volume": 0.5}, {**O, "speed": 1.5, "freeze": 0.5}, dict(O)]
        _, encodes = self.build(options, fade_seconds=0.15)
        with mock.patch.object(ms.subprocess, "run") as run, mock.patch.object(ms, "has_audio", return_value=True), \
                mock.patch.object(ms, "probe_size", return_value=(1920, 1080)):
            ms.build_montage("a.mp4", self.cuts, 0, str(Path(self.tmp) / "plain.mp4"), options, (1080, 1920), fade_seconds=0.15)
        single = run.call_args.args[0]
        whole = single[single.index("-filter_complex") + 1].split(";")
        for i, cmd in enumerate(encodes[:3]):
            own = cmd[cmd.index("-filter_complex") + 1].split(";")
            self.assertEqual(own.pop(), f"[v0]fps={clip_cache.FPS}[vf]")
            expected = [p.replace(f"[{i}:", "[0:").replace(f"[v{i}]", "[v0]").replace(f"[a{i}]", "[a0]")
                        for p in whole if p.endswith(f"[v{i}]") or p.endswith(f"[a{i}]")]
            self.assertEqual(own, expected, f"clip {i}")

    def test_a_voice_becomes_the_clips_second_input(self):
        voice = Path(self.tmp) / "voice.wav"
        voice.write_bytes(b"v")
        options = [{**O, "voice": str(voice)}, dict(O), dict(O)]
        _, encodes = self.build(options)
        first = encodes[0]
        self.assertEqual([first[i + 1] for i, a in enumerate(first) if a == "-i"], ["a.mp4", str(voice)])
        self.assertIn("[1:a]asetpts=", first[first.index("-filter_complex") + 1])

    def test_normalized_clips_measure_through_the_cache(self):
        options = [dict(O) for _ in self.cuts]
        with mock.patch.object(ms, "measure_loudness", return_value=-20.0) as measure:
            self.build(options, normalize=True)
            self.build(options, normalize=True)
        self.assertEqual(measure.call_count, 3)

    def test_the_grade_table_lives_in_the_cache_so_its_key_is_stable(self):
        options = [{**O, "saturation": 1.4}, dict(O), dict(O)]
        self.build(options)
        _, encodes = self.build(options)
        self.assertEqual(len(encodes), 1)
        self.assertTrue(list(self.cache.dir.glob("grade-*.cube")))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class RealRender(unittest.TestCase):
    def test_a_cached_render_matches_the_one_pass_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = str(Path(tmp) / "src.mp4")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=6",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-shortest", "-pix_fmt", "yuv420p", src], check=True)
            cuts = [(0, 2, None), (2, 4, None), (4, 6, None)]
            opts = [{**O, "fit": "fill", "zoom": 1.2}, {**O, "speed": 2.0, "transition": "dip", "tlen": 0.4}, {**O, "freeze": 0.5}]
            cache = clip_cache.ClipCache(Path(tmp) / "cache")
            plain, cached, again = (str(Path(tmp) / f"{n}.mp4") for n in ("plain", "cached", "again"))
            a = ms.build_montage(src, cuts, 0, plain, opts, (160, 120))
            b = ms.build_montage(src, cuts, 0, cached, opts, (160, 120), cache=cache)
            c = ms.build_montage(src, cuts, 0, again, opts, (160, 120), cache=cache)
            self.assertEqual((a, b, c), (a, a, a))
            self.assertEqual((cache.hits, cache.misses), (3, 3))
            for path in (plain, cached, again):
                self.assertAlmostEqual(ms.probe_duration(path), a, delta=0.15)
                self.assertEqual(ms.probe_size(path), (160, 120))


def tone_source(path, colour, hz, seconds=3):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color={colour}:s=320x240:r=60000/1001:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency={hz}:sample_rate=44100:d={seconds}", "-shortest", "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", "-c:a", "aac", str(path)], check=True)


def centre_pixel(video, frame):
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"select='eq(n,{frame})',crop=2:2:(iw-2)/2:(ih-2)/2,format=rgb24",
                          "-vsync", "0", "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True, check=True)
    return tuple(out.stdout[:3])


def tone_at(video, start, length=0.05):
    """The rough frequency of the sound in a window, from zero crossings of a mono 16 kHz read."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    samples = [int.from_bytes(out[i:i + 2], "little", signed=True) for i in range(0, len(out) - 1, 2)]
    crossings = sum(1 for a, b in zip(samples, samples[1:]) if (a < 0) != (b < 0))
    return crossings / 2 / length


def name_of(rgb):
    r, g, b = rgb
    return "red" if r > 150 > g and b < 100 else "green" if g > 100 > r and b < 100 else "blue" if b > 150 > r and g < 100 else str(rgb)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class RealShort(unittest.TestCase):
    """A Short made from kept clips has every cut where the cut list says, in picture and in sound."""

    def test_seams_land_on_the_cut_list_and_a_second_render_reuses_every_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for colour, hz in (("red", 300), ("green", 600), ("blue", 900)):
                tone_source(tmp / f"{colour}.mp4", colour, hz)
            cuts = tmp / "cuts.txt"
            cuts.write_text(f"{tmp}/red.mp4 | 0 - 1.1\n@speed 2\n{tmp}/green.mp4 | 0 - 1.4\n{tmp}/blue.mp4 | 0 - 1.3\n")
            out = tmp / "short.mp4"
            cmd = [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/make_short.py"), "--cuts", str(cuts), "--card", "--layout", "bare",
                   "--cache", str(tmp / "cache"), "-o", str(out)]
            first = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("0 reused, 3 rendered", first.stderr)
            self.assertAlmostEqual(ms.probe_duration(out), 3.1, delta=0.05)
            self.assertEqual([name_of(centre_pixel(out, n)) for n in (0, 32, 33, 53, 54, 92)], ["red", "red", "green", "green", "blue", "blue"])
            self.assertAlmostEqual(tone_at(out, 1.0), 300, delta=60)
            self.assertAlmostEqual(tone_at(out, 1.12), 600, delta=90)
            self.assertAlmostEqual(tone_at(out, 1.72), 600, delta=90)
            self.assertAlmostEqual(tone_at(out, 1.82), 900, delta=120)
            second = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("3 reused, 0 rendered", second.stderr)
            self.assertAlmostEqual(ms.probe_duration(out), 3.1, delta=0.05)


class CommandLine(unittest.TestCase):
    def main(self, tmp, extra, **patches):
        src = Path(tmp) / "src.mp4"
        src.write_bytes(b"x")
        with mock.patch.object(ms, "stack_lanes"), mock.patch.object(ms, "render_card", return_value=(100, 100, 0, 0)), \
                mock.patch.object(ms, "probe_size", return_value=(1920, 1080)), mock.patch.object(ms, "has_audio", return_value=True), \
                mock.patch.object(ms.subprocess, "run") as run, mock.patch.object(ms, "mix_audio"), \
                mock.patch.multiple(ms, **patches), \
                mock.patch.object(sys, "argv", ["make_short.py", str(src), "--card", "--cache", str(Path(tmp) / "c"), "-o", str(Path(tmp) / "o.mp4"), *extra]):
            ms.main()
        return run.call_args.args[0]

    def test_the_cache_flag_is_passed_to_every_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            build = mock.Mock(return_value=3.0)
            self.main(tmp, ["--cuts", "0:00 - 0:03\n@lane bottom\n0:00 - 0:03", "--template", "split"], build_montage=build)
            self.assertEqual(build.call_count, 2)
            for call in build.call_args_list:
                self.assertIsInstance(call.kwargs["cache"], clip_cache.ClipCache)
            self.assertTrue((Path(tmp) / "c").is_dir())

    def test_plain_cuts_feed_the_kept_clips_straight_into_the_final_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = [str(Path(tmp) / f"k{n}.mov") for n in range(2)]
            kept = mock.Mock(return_value=(files, [3.0, 2.0]))
            build = mock.Mock(return_value=5.0)
            with mock.patch.object(clip_cache, "write_list", wraps=clip_cache.write_list) as listed:
                cmd = self.main(tmp, ["--cuts", "0:00 - 0:03, 0:04 - 0:06"], cached_clip_files=kept, build_montage=build)
            build.assert_not_called()
            self.assertEqual(cmd[cmd.index("-f") + 1], "concat")
            self.assertEqual(cmd[cmd.index("-i", cmd.index("-f")) + 1], str(listed.call_args.args[1]))
            self.assertEqual(list(listed.call_args.args[0]), files)
            self.assertEqual(cmd[cmd.index("-t") + 1], "5.0")

    def test_a_transition_still_joins_through_the_montage(self):
        with tempfile.TemporaryDirectory() as tmp:
            kept = mock.Mock()
            build = mock.Mock(return_value=5.0)
            cmd = self.main(tmp, ["--cuts", "0:00 - 0:03\n@transition dip\n0:04 - 0:06"], cached_clip_files=kept, build_montage=build)
            kept.assert_not_called()
            build.assert_called_once()
            self.assertNotIn("concat", cmd)


if __name__ == "__main__":
    unittest.main()
