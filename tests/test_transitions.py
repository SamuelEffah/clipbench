import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts import clipper, make_short  # noqa: E402

O = make_short.DEFAULT_OPTIONS


class TransitionMathTests(unittest.TestCase):
    def test_a_transition_overlaps_the_two_clips(self):
        self.assertEqual(make_short.seam_overlaps([3, 2], [("none", 0.3), ("zoom", 0.3)]), [0.0, 0.3])
        self.assertAlmostEqual(make_short.joined_length([3, 2], [("none", 0.3), ("zoom", 0.3)]), 4.7)

    def test_the_first_clip_and_cuts_have_no_overlap(self):
        self.assertEqual(make_short.seam_overlaps([3, 2], [("flash", 0.5), ("none", 0.5)]), [0.0, 0.0])

    def test_a_transition_is_held_to_half_the_shorter_clip(self):
        self.assertEqual(make_short.seam_overlaps([4, 0.8], [("none", 0.3), ("dip", 1.5)]), [0.0, 0.4])

    def test_captions_follow_the_overlap(self):
        cuts = [(0, 3, None), (3, 5, None)]
        opts = [{**O, "caption": "a"}, {**O, "caption": "b", "transition": "flash", "tlen": 0.5}]
        cues = make_short.caption_cues(cuts, opts)
        self.assertEqual([(round(a, 2), round(b, 2)) for a, b, *_ in cues], [(0.0, 3.0), (2.5, 4.5)])

    def test_spoken_captions_end_where_the_next_clip_starts(self):
        cuts = [(0, 3, None), (3, 5, None)]
        opts = [{**O, "words": [["hi", 0.2, 2.9]], "capmode": "phrase"},
                {**O, "words": [["yo", 0.1, 0.5]], "capmode": "phrase", "transition": "flash", "tlen": 0.5}]
        cues = make_short.caption_cues(cuts, opts)
        self.assertEqual([(round(a, 2), round(b, 2), t) for a, b, t, *_ in cues], [(0.2, 2.5, "hi"), (2.6, 3.35, "yo")])

    def test_a_spoken_caption_with_no_transition_after_it_keeps_its_hold(self):
        cuts = [(0, 3, None), (3, 5, None)]
        opts = [{**O, "words": [["hi", 0.2, 2.5]], "capmode": "phrase"}, {**O, "words": [["yo", 0.1, 0.5]], "capmode": "phrase"}]
        cues = make_short.caption_cues(cuts, opts)
        self.assertEqual(round(cues[0][1], 2), 2.85)

    def test_cut_list_reads_the_transition(self):
        cut = make_short.read_cuts("0:00 - 0:02\n@transition whip\n@tlen 0.4\n0:03 - 0:05")[1]
        self.assertEqual((cut[3]["transition"], cut[3]["tlen"]), ("whip", 0.4))

    def test_cut_list_rejects_an_unknown_transition(self):
        with self.assertRaises(SystemExit):
            make_short.read_cuts("@transition spin\n0:00 - 0:02")

    def test_the_server_exports_the_transition_and_its_length(self):
        clip = {"in": 0, "out": 2, "src": "x.mp4", "transition": "iris", "tlen": 0.4}
        self.assertEqual(clipper.top_length([{**clip, "transition": "none"}, clip]), 3.6)


class TransitionRenderTests(unittest.TestCase):
    def test_every_transition_renders_at_the_overlapped_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = str(Path(tmp) / "src.mp4")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=6",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-shortest", "-pix_fmt", "yuv420p", src], check=True)
            for name in [n for n in make_short.TRANSITIONS if n != "none"]:
                cuts = [(0, 2, None), (2, 4, None), (4, 6, None)]
                opts = [dict(O), {**O, "transition": name, "tlen": 0.4}, dict(O)]
                dest = str(Path(tmp) / f"{name}.mp4")
                length = make_short.build_montage(src, cuts, 0, dest, opts)
                self.assertAlmostEqual(length, 5.6, places=2, msg=name)
                self.assertAlmostEqual(make_short.probe_duration(dest), 5.6, delta=0.15, msg=name)

    def test_the_first_clip_can_appear_out_of_black_without_changing_the_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = str(Path(tmp) / "src.mp4")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=red:s=320x240:rate=30:duration=4",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-shortest", "-pix_fmt", "yuv420p", src], check=True)
            for name in [n for n in make_short.TRANSITIONS if n != "none"]:
                for second in (False, True):
                    cuts = [(0, 2, None), (2, 4, None)] if second else [(0, 2, None)]
                    opts = [{**O, "transition": name, "tlen": 0.5}] + ([dict(O)] if second else [])
                    dest = str(Path(tmp) / f"{name}{second}.mp4")
                    length = make_short.build_montage(src, cuts, 0, dest, opts)
                    self.assertAlmostEqual(length, 4.0 if second else 2.0, places=2, msg=name)
                    self.assertAlmostEqual(make_short.probe_duration(dest), length, delta=0.15, msg=name)
            first = self.pixel(str(Path(tmp) / "flashFalse.mp4"), 0)
            self.assertLess(max(first), 60)

    def pixel(self, path, frame):
        out = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"select='eq(n,{frame})',scale=2:2,format=rgb24",
                              "-fps_mode", "passthrough", "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True)
        return tuple(out.stdout[:3])


@unittest.skipUnless(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode == 0, "ffmpeg isn't installed")
class CustomTransitionTests(unittest.TestCase):
    def frame(self, name, frame):
        expr = make_short.TRANSITION_EXPR[name]
        graph = f"[0][1]xfade=transition=custom:expr='{expr}':duration=1:offset=0.5,select='eq(n,{frame})',scale=2:2,format=rgb24"
        out = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=64x64:r=30:d=2", "-f", "lavfi", "-i", "color=blue:s=64x64:r=30:d=2",
                              "-filter_complex", graph, "-fps_mode", "passthrough", "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True)
        return tuple(out.stdout[:3])

    def test_the_outgoing_clip_is_shown_first_and_the_incoming_clip_last(self):
        for name in make_short.TRANSITION_EXPR:
            with self.subTest(name):
                first, last = self.frame(name, 15), self.frame(name, 43)
                self.assertGreater(first[0], 200)
                self.assertLess(first[2], 50)
                self.assertGreater(last[2], 200)
                self.assertLess(last[0], 50)

    def test_a_zoom_blends_both_pictures_in_the_middle(self):
        for name in ("zoom_in", "zoom_punch", "zoom_out"):
            with self.subTest(name):
                red, _, blue = self.frame(name, 29)
                self.assertGreater(red, 30)
                self.assertGreater(blue, 30)


if __name__ == "__main__":
    unittest.main()
