import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import clipper  # noqa: E402
import embedded_subs  # noqa: E402

SRT = """1
00:00:01,000 --> 00:00:03,000
<font face="x"><b>Hello there friend</b></font>

2
00:00:03,000 --> 00:00:04,000
[roar]

3
00:00:05,000 --> 00:00:06,000
{\\an8}Second line
"""


def make_video(folder, subs):
    src = str(Path(folder) / "ep.mkv")
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=64x64:r=10:d=8"]
    for n, path in enumerate(subs):
        cmd += ["-i", path]
    cmd += ["-map", "0:v"] + [a for n in range(len(subs)) for a in ("-map", f"{n + 1}:0")]
    cmd += ["-c:v", "libx264", "-c:s", "srt"]
    for n, name in enumerate(["Forced", "English"]):
        if n < len(subs):
            cmd += [f"-metadata:s:s:{n}", "language=eng", f"-metadata:s:s:{n}", f"title={name}"]
    return src, subprocess.run(cmd + [src], capture_output=True)


@unittest.skipUnless(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode == 0, "ffmpeg isn't installed")
class EmbeddedSubtitleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        forced = Path(self.tmp.name) / "forced.srt"
        full = Path(self.tmp.name) / "full.srt"
        forced.write_text("1\n00:00:00,500 --> 00:00:01,500\nSIGN\n")
        full.write_text(SRT)
        self.src, made = make_video(self.tmp.name, [str(forced), str(full)])
        self.assertEqual(made.returncode, 0, made.stderr)
        embedded_subs.english_stream.cache_clear()
        embedded_subs.all_cues.cache_clear()

    def test_the_full_english_track_beats_the_forced_one(self):
        words = embedded_subs.words(self.src, 0, 8)
        self.assertEqual([w[0] for w in words], ["Hello", "there", "friend", "Second", "line"])

    def test_an_ai_dub_track_loses_to_the_real_english_one_even_when_it_comes_first(self):
        dub = Path(self.tmp.name) / "dub.srt"
        full = Path(self.tmp.name) / "full.srt"
        dub.write_text("1\n00:00:01,000 --> 00:00:03,000\nDUB WORDS HERE\n")
        full.write_text(SRT)
        src = str(Path(self.tmp.name) / "dubfirst.mkv")
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=64x64:r=10:d=8", "-i", str(dub), "-i", str(full),
               "-map", "0:v", "-map", "1:0", "-map", "2:0", "-c:v", "libx264", "-c:s", "srt",
               "-metadata:s:s:0", "language=en", "-metadata:s:s:0", "title=Dubtitle(AI)",
               "-metadata:s:s:1", "language=eng", "-metadata:s:s:1", "title=English [Group]", src]
        self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
        embedded_subs.english_stream.cache_clear()
        embedded_subs.all_cues.cache_clear()
        words = embedded_subs.words(src, 0, 8)
        self.assertEqual([w[0] for w in words], ["Hello", "there", "friend", "Second", "line"])

    def test_words_are_timed_from_the_start_of_the_range(self):
        words = embedded_subs.words(self.src, 1, 7)
        self.assertAlmostEqual(words[0][1], 0.0, delta=0.15)
        self.assertAlmostEqual(words[2][2], 2.0, delta=0.15)

    def test_sound_notes_are_left_out(self):
        self.assertNotIn("[roar]", " ".join(w[0] for w in embedded_subs.words(self.src, 0, 8)))

    def test_a_quiet_stretch_gives_no_words_but_is_not_a_missing_track(self):
        self.assertEqual(embedded_subs.words(self.src, 6.5, 8), [])

    def test_a_video_without_subtitles_gives_none(self):
        plain = str(Path(self.tmp.name) / "plain.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=64x64:r=10:d=2", plain], check=True)
        self.assertIsNone(embedded_subs.words(plain, 0, 2))

    def test_a_caption_job_reads_the_subtitles_without_listening(self):
        clipper.transcripts["j"] = {"id": "j", "state": "working"}
        self.addCleanup(clipper.transcripts.pop, "j", None)
        clipper.listen("j", None, self.src, 0, 8, True, "translate")
        self.assertEqual(clipper.transcripts["j"]["state"], "done")
        self.assertEqual(clipper.transcripts["j"]["text"], "Hello there friend Second line")


if __name__ == "__main__":
    unittest.main()


class TidyCuesTests(unittest.TestCase):
    def test_long_tracks_do_not_compare_every_line_to_all_earlier_lines(self):
        class CountedText(str):
            comparisons = 0
            __hash__ = str.__hash__

            def __eq__(self, other):
                CountedText.comparisons += 1
                return super().__eq__(other)

        lines = [(float(n), n + 0.5, CountedText(f"Line {n}")) for n in range(2000)]
        self.assertEqual(len(embedded_subs.tidy(lines)), len(lines))
        self.assertLess(CountedText.comparisons, len(lines) * 10)

    def test_repeated_lines_merge_across_other_overlapping_dialogue(self):
        lines = [(1.0, 4.0, "Hello"), (2.0, 3.0, "Other speaker"), (3.5, 5.0, "Hello"), (7.0, 8.0, "Hello")]
        self.assertEqual(embedded_subs.tidy(lines), [(1.0, 5.0, "Hello"), (2.0, 3.0, "Other speaker"), (7.0, 8.0, "Hello")])

    def test_per_frame_repeats_become_one_line(self):
        frames = [(3.42 + n * 0.04, 3.46 + n * 0.04, "You ran away.") for n in range(15)]
        out = embedded_subs.tidy([(1.3, 3.42, "You ran away.")] + frames)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0][0], out[0][2]), (1.3, "You ran away."))
        self.assertAlmostEqual(out[0][1], frames[-1][1])

    def test_doubled_layers_are_kept_once(self):
        self.assertEqual(embedded_subs.tidy([(5.76, 5.84, "Team"), (5.76, 5.84, "Team")]), [(5.76, 5.84, "Team")])

    def test_drawing_commands_are_not_speech(self):
        self.assertEqual(embedded_subs.tidy([(6.0, 6.1, "m 0 0 l 1125 0 1125 150 0 120"), (7.0, 8.0, "Hello")]), [(7.0, 8.0, "Hello")])

    def test_the_same_words_said_again_later_stay_separate(self):
        said = [(1.0, 1.5, "No."), (3.0, 3.5, "No.")]
        self.assertEqual(embedded_subs.tidy(said), said)

    def test_different_lines_are_untouched_and_ordered(self):
        lines = [(4.0, 5.0, "Second"), (1.0, 2.0, "First")]
        self.assertEqual(embedded_subs.tidy(lines), [(1.0, 2.0, "First"), (4.0, 5.0, "Second")])
