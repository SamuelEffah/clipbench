import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts import clipper, make_short  # noqa: E402


class LaneParseTests(unittest.TestCase):
    def test_lane_marks_the_next_cut(self):
        cuts = make_short.read_cuts("0:01 - 0:03\n@lane bottom\n0:05 - 0:09")
        self.assertEqual([c[3]["lane"] for c in cuts], ["top", "bottom"])

    def test_unknown_lane_is_rejected(self):
        with self.assertRaises(SystemExit):
            make_short.read_cuts("@lane middle\n0:01 - 0:03")

    def test_lane_split_keeps_order_within_each_lane(self):
        text = "0:01 - 0:02\n@lane bottom\n0:03 - 0:04\n0:05 - 0:06\n@lane bottom\n0:07 - 0:08"
        cuts = make_short.read_cuts(text)
        (top, _), (bottom, _) = make_short.lane_split([c[:3] for c in cuts], [c[3] for c in cuts])
        self.assertEqual([c[0] for c in top], [1, 5])
        self.assertEqual([c[0] for c in bottom], [3, 7])


class GeometryTests(unittest.TestCase):
    def test_every_layout_fills_the_frame_with_even_lanes(self):
        for w, h in ((1080, 1920), (1080, 1350), (1080, 1080), (1920, 1080)):
            for template in ("split", "three", "four"):
                sizes = make_short.lane_sizes(w, h, template)
                self.assertEqual(len(sizes), make_short.LANE_COUNT[template])
                self.assertTrue(all(x % 2 == 0 and y % 2 == 0 and x > 0 and y > 0 for x, y in sizes))
                area = sum(x * y for x, y in sizes)
                self.assertEqual(area, w * h)

    def test_three_is_one_row_over_two_and_four_is_a_grid(self):
        top, bl, br = make_short.lane_sizes(1080, 1920, "three")
        self.assertEqual((top[0], bl[0] + br[0]), (1080, 1080))
        self.assertEqual(top[1], bl[1])
        tl, tr, bl, br = make_short.lane_sizes(1080, 1920, "four")
        self.assertEqual((tl[0] + tr[0], bl[0] + br[0], tl[1] + bl[1]), (1080, 1080, 1920))

    def test_a_dragged_seam_still_fills_the_frame_with_even_lanes(self):
        for row in (0.2, 0.33, 0.5, 0.67, 0.8):
            for col in (0.2, 0.5, 0.8):
                for template in ("split", "three"):
                    sizes = make_short.lane_sizes(1080, 1920, template, row, col)
                    self.assertTrue(all(x % 2 == 0 and y % 2 == 0 for x, y in sizes))
                    self.assertEqual(sum(x * y for x, y in sizes), 1080 * 1920)
        top, bl, br = make_short.lane_sizes(1080, 1920, "three", 0.67, 0.25)
        self.assertEqual((top[1] + bl[1], bl[0] + br[0]), (1920, 1080))
        self.assertGreater(top[1], bl[1])
        self.assertLess(bl[0], br[0])

    def test_out_of_range_seams_are_clamped_and_four_ignores_them(self):
        top, bottom = make_short.lane_sizes(1080, 1920, "split", 0.99)
        self.assertEqual(top[1], make_short.halves(1920, 0.8)[0])
        self.assertEqual(make_short.lane_sizes(1080, 1920, "four", 0.7, 0.3), make_short.lane_sizes(1080, 1920, "four"))

    def test_a_project_without_split_fields_renders_as_before(self):
        self.assertEqual(make_short.lane_sizes(1080, 1920, "three"), make_short.lane_sizes(1080, 1920, "three", 0.5, 0.5))
        self.assertEqual(make_short.halves(1920), (960, 960))
        self.assertEqual(make_short.halves(1350), (676, 674))

    def test_halves_are_even_and_fill_the_frame(self):
        for h in (1080, 1350, 1920):
            top, bottom = make_short.halves(h)
            self.assertEqual((top % 2, bottom % 2, top + bottom), (0, 0, h))

    def test_each_format_gets_its_own_canvas(self):
        for fmt, (w, h) in make_short.FORMATS.items():
            geo = make_short.card_geometry((w, h), "a hook", "title", fmt)
            self.assertEqual((geo["width"], geo["height"]), (w, h))
            self.assertLessEqual(geo["clip_w"], w)
            self.assertLessEqual(geo["top"] + geo["header_h"] + geo["text_block"] + geo["clip_h"], h)

    def test_clip_area_fills_the_room_when_no_clip_size_is_given(self):
        geo = make_short.card_geometry((1080, 1080), "", "bare", "1:1")
        self.assertEqual((geo["clip_w"], geo["clip_h"], geo["top"]), (1080, 1080, 0))

    def test_widescreen_clip_covers_the_whole_frame(self):
        geo = make_short.card_geometry((1920, 1080), "", "bare", "16:9")
        self.assertEqual((geo["clip_w"], geo["clip_h"], geo["top"]), (1920, 1080, 0))

    def test_only_a_hook_takes_room_the_clip_covers_the_rest(self):
        geo = make_short.card_geometry((1920, 1080), "a hook", "title", "16:9")
        covered = geo["top"] + geo["header_h"] + geo["text_block"] + geo["clip_h"]
        self.assertLessEqual(1080 - covered, 1, "the clip height is rounded down to even, which can leave one row")

    def test_vertical_clip_covers_the_whole_frame_too(self):
        geo = make_short.card_geometry((1080, 1920), "", "bare", "9:16")
        self.assertEqual((geo["clip_w"], geo["clip_h"], geo["top"]), (1080, 1920, 0))

    def test_a_vertical_hook_clears_the_status_bar(self):
        geo = make_short.card_geometry((1080, 1920), "a hook", "title", "9:16")
        self.assertEqual(geo["top"], make_short.TOP_MIN)

    def test_a_caption_sits_on_the_clip_above_its_bottom_edge(self):
        x, y, anchor = make_short.caption_home((1080, 1920), "9:16", 1920)
        self.assertEqual((x, anchor), (0.5, 2))
        self.assertAlmostEqual(y * 1920, 1920 - make_short.BOTTOM_SAFE - 20, delta=1)
        _, y169, _ = make_short.caption_home((1920, 1080), "16:9", 1080)
        self.assertAlmostEqual(y169 * 1080, 1080 - make_short.DEFAULT_CAPTION_INSET, delta=1)

    def test_an_unmoved_caption_takes_the_home_point_until_one_is_moved(self):
        home = (0.5, 0.8, 2)
        cuts = make_short.read_cuts("@caption a\n0:01 - 0:02\n@caption b\n@capx 0.2\n@capy 0.3\n0:03 - 0:04")
        cues = make_short.caption_cues([c[:3] for c in cuts], [c[3] for c in cuts], home)
        self.assertEqual([c[3] for c in cues], [home, (0.2, 0.3)])
        self.assertEqual(make_short.ass_place([home], (1080, 1920)), "{\\an2\\pos(540,1536)}")

    def test_a_given_clip_size_keeps_its_shape(self):
        geo = make_short.card_geometry((1080, 1920), "", "bare", "9:16", (1920, 1080))
        self.assertAlmostEqual(geo["clip_w"] / geo["clip_h"], 1920 / 1080, places=1)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.video = Path(self.dir.name) / "a.mp4"
        self.video.write_bytes(b"x")
        self.shorts = Path(self.dir.name) / "shorts"
        for name, value in (("PROJECT_DIR", Path(self.dir.name)), ("SHORT_DIR", self.shorts)):
            patch = mock.patch.object(clipper, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def clip(self, **extra):
        return {"src": str(self.video), "in": 1, "out": 3, **extra}

    def export(self, project):
        return clipper.export_cuts("ln", project)

    def test_the_command_writes_where_the_render_button_does(self):
        (self.shorts / "007_ln").mkdir(parents=True)
        _, command = self.export({"clips": [self.clip()]})
        self.assertTrue(command.endswith(f"-o {self.shorts / '007_ln' / 'video.mp4'}"))

    def test_split_writes_the_bottom_lane(self):
        text, command = self.export({"template": "split", "clips": [self.clip(), self.clip(lane="bottom")]})
        self.assertEqual(text.count("@lane bottom"), 1)
        self.assertIn("--template split", command)

    def test_full_template_leaves_bottom_clips_out(self):
        text, command = self.export({"clips": [self.clip(), self.clip(lane="bottom")]})
        self.assertNotIn("@lane", text)
        self.assertEqual(text.count(" | "), 1)
        self.assertNotIn("--template", command)

    def test_a_muted_lane_writes_silent_clips(self):
        clips = [self.clip(), self.clip(lane="bottom", volume=0.8), self.clip(lane="bottom")]
        text, _ = self.export({"template": "split", "laneMute": {"bottom": True}, "clips": clips})
        self.assertEqual(text.count("@volume 0\n") + text.count("@volume 0 "), 2)

    def test_a_muted_lane_leaves_the_others_alone(self):
        text, _ = self.export({"template": "split", "laneMute": {"bottom": True}, "clips": [self.clip(volume=0.5), self.clip(lane="bottom")]})
        self.assertIn("@volume 0.5", text)

    def test_no_mute_map_changes_nothing(self):
        text, _ = self.export({"template": "split", "clips": [self.clip(), self.clip(lane="bottom")]})
        self.assertNotIn("@volume", text)

    def test_three_and_four_write_their_lanes(self):
        clips = [self.clip(), self.clip(lane="bottom"), self.clip(lane="third"), self.clip(lane="fourth")]
        text, command = self.export({"template": "three", "clips": clips})
        self.assertIn("@lane third", text)
        self.assertNotIn("@lane fourth", text)
        self.assertIn("--template three", command)
        text, _ = self.export({"template": "four", "clips": clips})
        self.assertIn("@lane fourth", text)

    def test_fill_and_fit_are_one_lane_layouts(self):
        for template in ("fill", "fit"):
            text, command = self.export({"template": template, "clips": [self.clip(), self.clip(lane="bottom")]})
            self.assertIn(f"--template {template}", command)
            self.assertNotIn("@lane", text)

    def test_a_lane_a_layout_lacks_is_left_out(self):
        text, _ = self.export({"template": "split", "clips": [self.clip(), self.clip(lane="third")]})
        self.assertNotIn("@lane", text)

    def test_split_needs_a_top_clip(self):
        with self.assertRaises(ValueError):
            self.export({"template": "split", "clips": [self.clip(lane="bottom")]})

    def test_format_and_template_become_flags(self):
        _, command = self.export({"format": "1:1", "clips": [self.clip()]})
        self.assertIn("--format 1:1", command)

    def test_unknown_format_is_rejected(self):
        with self.assertRaises(ValueError):
            self.export({"format": "3:2", "clips": [self.clip()]})


if __name__ == "__main__":
    unittest.main()


class SegmentShapeTests(unittest.TestCase):
    def test_every_clip_is_forced_to_square_pixels_so_they_can_be_joined(self):
        options = [{**make_short.DEFAULT_OPTIONS, "effect": effect, "fit": "fill"} for effect in ("zoom_in", "zoom_out", "none")]
        cuts = [(0.0, 2.0, "a.mp4")] * 3
        with mock.patch.object(make_short.subprocess, "run") as run, \
                mock.patch.object(make_short, "has_audio", return_value=False), \
                mock.patch.object(make_short, "probe_size", return_value=(1920, 1080)):
            make_short.build_montage("a.mp4", cuts, 0, "out.mp4", options, (1080, 1920))
        graph = run.call_args.args[0][run.call_args.args[0].index("-filter_complex") + 1]
        for i in range(3):
            segment = next(p for p in graph.split(";") if p.endswith(f"[v{i}]"))
            self.assertTrue(segment.endswith(f",setsar=1[v{i}]"), segment)


class CaptionPositionTests(unittest.TestCase):
    def test_a_moved_caption_is_pinned_to_its_point(self):
        self.assertEqual(make_short.ass_place([(0.5, 0.25)], (1080, 1920)), "{\\an5\\pos(540,480)}")
        self.assertEqual(make_short.ass_place([], (1080, 1920)), "")
        self.assertEqual(make_short.ass_place([None], (1080, 1920)), "")

    def test_the_cut_list_carries_the_position_into_the_cue(self):
        cuts = make_short.read_cuts("@caption hi\n@capx 0.4\n@capy 0.8\n0:01 - 0:03\n@caption plain\n0:05 - 0:06")
        cues = make_short.caption_cues([c[:3] for c in cuts], [c[3] for c in cuts])
        self.assertEqual([c[3] for c in cues], [(0.4, 0.8), (0.4, 0.8)])

    def test_a_position_outside_the_frame_is_rejected(self):
        with self.assertRaises(SystemExit):
            make_short.read_cuts("@capx 1.5\n0:01 - 0:03")

    def test_the_ass_file_places_only_the_moved_caption(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "c.ass"
            make_short.write_ass([(0, 1, "moved", (0.5, 0.5)), (1, 2, "default", None)], 100, dest, (1080, 1920))
            lines = [l for l in dest.read_text().splitlines() if l.startswith("Dialogue")]
        self.assertIn("{\\an5\\pos(540,960)}moved", lines[0])
        self.assertTrue(lines[1].endswith(",,default"))


class CaptionExportTests(ExportTests):
    def test_position_is_written_only_when_the_caption_was_moved(self):
        text, _ = self.export({"clips": [self.clip(caption="hi")]})
        self.assertNotIn("@capx", text)
        text, _ = self.export({"clips": [self.clip(caption="hi", capX=0.4, capY=0.75)]})
        self.assertIn("@capx 0.4", text)
        self.assertIn("@capy 0.75", text)

    def test_a_position_outside_the_frame_is_refused(self):
        with self.assertRaises(ValueError):
            self.export({"clips": [self.clip(caption="hi", capX=2, capY=0.5)]})


class CaptionSizeTests(unittest.TestCase):
    def test_size_scales_the_ass_text_and_outline(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "c.ass"
            make_short.write_ass([(0, 1, "big", None)], 100, dest, (1080, 1920), 100)
            style = next(l for l in dest.read_text().splitlines() if l.startswith("Style:"))
        fields = style.split(",")
        self.assertEqual((fields[2], fields[9]), ("100", "6"))

    def test_default_size_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "c.ass"
            make_short.write_ass([(0, 1, "x", None)], 100, dest, (1080, 1920))
            style = next(l for l in dest.read_text().splitlines() if l.startswith("Style:"))
        self.assertEqual(style.split(",")[2], str(make_short.SUB_FONT_SIZE))


class CaptionSizeFlagTests(ExportTests):
    def test_a_chosen_size_becomes_a_flag_and_the_default_does_not(self):
        _, command = self.export({"capSize": 90, "clips": [self.clip()]})
        self.assertIn("--caption-size 90", command)
        _, command = self.export({"capSize": 0, "clips": [self.clip()]})
        self.assertNotIn("--caption-size", command)

    def test_a_size_out_of_range_is_refused(self):
        with self.assertRaises(ValueError):
            self.export({"capSize": 500, "clips": [self.clip()]})


class ClipFadeTests(unittest.TestCase):
    def options(self, **extra):
        return {**make_short.DEFAULT_OPTIONS, **extra}

    def test_no_fade_adds_nothing(self):
        self.assertEqual(make_short.video_fade(self.options(), 4.0), "")
        self.assertEqual(make_short.audio_fade(self.options(), 4.0), "")

    def test_fades_run_at_the_clips_own_edges_in_picture_and_sound(self):
        opt = self.options(fadein=0.5, fadeout=1.0)
        self.assertEqual(make_short.video_fade(opt, 4.0), ",fade=t=in:st=0:d=0.500,fade=t=out:st=3.000:d=1.000")
        self.assertEqual(make_short.audio_fade(opt, 4.0), ",afade=t=in:d=0.500,afade=t=out:st=3.000:d=1.000")

    def test_fades_never_overlap_on_a_short_clip(self):
        self.assertEqual(make_short.clip_fades(self.options(fadein=3, fadeout=3), 2.0), (1.0, 1.0))

    def test_the_cut_list_reads_and_limits_fades(self):
        cuts = make_short.read_cuts("@fadein 0.5\n@fadeout 2\n0:01 - 0:05")
        self.assertEqual((cuts[0][3]["fadein"], cuts[0][3]["fadeout"]), (0.5, 2.0))
        with self.assertRaises(SystemExit):
            make_short.read_cuts("@fadein 5\n0:01 - 0:05")

    def test_every_clip_chain_carries_its_fade(self):
        options = [self.options(fadein=0.5), self.options(fadeout=0.5)]
        with mock.patch.object(make_short.subprocess, "run") as run, \
                mock.patch.object(make_short, "has_audio", return_value=True), \
                mock.patch.object(make_short, "probe_size", return_value=(1920, 1080)):
            make_short.build_montage("a.mp4", [(0.0, 2.0, "a.mp4")] * 2, 0, "out.mp4", options, (1080, 1920))
        graph = run.call_args.args[0][run.call_args.args[0].index("-filter_complex") + 1]
        self.assertIn("fade=t=in:st=0:d=0.500", graph)
        self.assertIn("fade=t=out:st=1.500:d=0.500", graph)
        self.assertIn("afade=t=in:d=0.500", graph)


class FadeExportTests(ExportTests):
    def test_fades_are_written_only_when_set_and_must_be_in_range(self):
        text, _ = self.export({"clips": [self.clip()]})
        self.assertNotIn("@fade", text)
        text, _ = self.export({"clips": [self.clip(fadeIn=0.5, fadeOut=1)]})
        self.assertIn("@fadein 0.5", text)
        self.assertIn("@fadeout 1", text)
        with self.assertRaises(ValueError):
            self.export({"clips": [self.clip(fadeIn=9)]})


class CaptionInheritTests(unittest.TestCase):
    def cues(self, text, home=None):
        cuts = make_short.read_cuts(text)
        return make_short.caption_cues([c[:3] for c in cuts], [c[3] for c in cuts], home)

    def test_a_new_caption_keeps_the_previous_position_size_and_turn_until_changed(self):
        cues = self.cues("@caption a\n@capx 0.3\n@capy 0.4\n@capscale 0.7\n@caprot 10\n0:01 - 0:02\n@caption b\n0:03 - 0:04\n"
                         "@caption c\n@capx 0.6\n@capy 0.2\n0:05 - 0:06")
        self.assertEqual([c[3:6] for c in cues], [((0.3, 0.4), 0.7, 10.0), ((0.3, 0.4), 0.7, 10.0), ((0.6, 0.2), 0.7, 10.0)])

    def test_a_clip_without_a_caption_still_passes_its_position_on(self):
        cues = self.cues("@capx 0.3\n@capy 0.4\n0:01 - 0:02\n@caption b\n0:03 - 0:04")
        self.assertEqual(cues[0][3], (0.3, 0.4))

    def test_size_and_turn_become_ass_overrides(self):
        tag = make_short.ass_place([(0.5, 0.5), 0.5, 20.0], (1080, 1920), 50)
        self.assertEqual(tag, "{\\an5\\pos(540,960)\\fs25\\bord3\\frz-20}")

    def test_size_and_turn_are_range_checked(self):
        for bad in ("@capscale 9", "@caprot 400"):
            with self.assertRaises(SystemExit):
                make_short.read_cuts(f"{bad}\n0:01 - 0:02")


class BottomLaneHoldTests(unittest.TestCase):
    def graph(self, **kwargs):
        cuts = [(0.0, 2.0, "a.mp4")] * 2
        options = [dict(make_short.DEFAULT_OPTIONS) for _ in cuts]
        with mock.patch.object(make_short.subprocess, "run") as run, \
                mock.patch.object(make_short, "has_audio", return_value=False):
            make_short.build_montage("a.mp4", cuts, 0, "out.mp4", options, (1080, 960), fade_seconds=0.15, **kwargs)
        graph = run.call_args.args[0][run.call_args.args[0].index("-filter_complex") + 1]
        return [next(p for p in graph.split(";") if p.endswith(f"[v{i}]")) for i in range(2)]

    def test_every_clip_dips_out_by_default(self):
        self.assertTrue(all("fade=t=out" in s for s in self.graph()))

    def test_a_held_lane_keeps_its_last_frame_bright(self):
        first, last = self.graph(hold_last=True)
        self.assertIn("fade=t=out", first)
        self.assertNotIn("fade=t=out", last)
        self.assertIn("fade=t=in", last)
