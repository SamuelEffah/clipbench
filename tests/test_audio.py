import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts import clipper, make_short  # noqa: E402


def tone(path, seconds, freq=440):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}", path], check=True)


def loudness(path, start, length):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-ss", str(start), "-t", str(length), "-i", path, "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    line = next((ln for ln in out.splitlines() if "mean_volume" in ln), "")
    return float(line.split("mean_volume:")[1].split("dB")[0]) if line else -99.0


class AudioMixTests(unittest.TestCase):
    def test_the_graph_trims_levels_fades_and_delays_each_sound(self):
        item = {"path": "x.mp3", "start": 1.5, "in": 2.0, "dur": 3.0, "volume": 0.5, "fadein": 0.5, "fadeout": 4.0}
        graph = make_short.audio_mix_graph([item])
        for part in ("atrim=start=2.000:duration=3.000", "volume=0.500", "afade=t=in:d=0.500", "afade=t=out:st=1.500:d=1.500", "adelay=delays=1500:all=1",
                     "amix=inputs=2:normalize=0:duration=first"):
            self.assertIn(part, graph)

    def test_a_sound_can_slide_from_one_level_to_another(self):
        item = {"path": "x.mp3", "start": 0, "in": 0.0, "dur": 10.0, "volume": 0.1, "volumeend": 0.3, "fadein": 0.0, "fadeout": 0.0}
        graph = make_short.audio_mix_graph([item])
        self.assertIn("volume='0.100+(0.300-0.100)*t/10.000':eval=frame", graph)
        steady = make_short.audio_mix_graph([{**item, "volumeend": 0.1}])
        self.assertIn("volume=0.100", steady)
        self.assertNotIn("eval=frame", steady)

    def test_the_end_level_defaults_to_the_start_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            sound = str(Path(tmp) / "a.wav")
            tone(sound, 1)
            spec = Path(tmp) / "x.json"
            spec.write_text(json.dumps([{"path": sound, "dur": 1, "volume": 0.4}]))
            self.assertEqual(make_short.load_audio_items(str(spec))[0]["volumeend"], 0.4)
            spec.write_text(json.dumps([{"path": sound, "dur": 1, "volume": 0.4, "volumeend": 0.9}]))
            self.assertEqual(make_short.load_audio_items(str(spec))[0]["volumeend"], 0.9)

    def test_a_bad_audio_list_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            sound = str(Path(tmp) / "a.wav")
            tone(sound, 1)
            for bad in ([{"path": "missing.wav", "dur": 1}], [{"path": sound, "dur": 1, "volume": 9}], [{"path": sound, "dur": 0}], {"path": sound}):
                spec = Path(tmp) / "x.json"
                spec.write_text(json.dumps(bad))
                with self.assertRaises(SystemExit):
                    make_short.load_audio_items(str(spec))

    def test_a_sound_is_heard_only_where_it_is_placed(self):
        with tempfile.TemporaryDirectory() as tmp:
            video, sound = str(Path(tmp) / "v.mp4"), str(Path(tmp) / "s.wav")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=160x90:d=4:r=30", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=4",
                            "-shortest", "-pix_fmt", "yuv420p", video], check=True)
            tone(sound, 5)
            before = make_short.probe_duration(video)
            make_short.mix_audio(video, [{"path": sound, "start": 2.0, "in": 0.0, "dur": 1.0, "volume": 1.0, "fadein": 0.0, "fadeout": 0.0}])
            self.assertAlmostEqual(make_short.probe_duration(video), before, delta=0.1)
            self.assertLess(loudness(video, 0, 1.5), -60)
            self.assertGreater(loudness(video, 2.1, 0.8), -30)
            self.assertLess(loudness(video, 3.2, 0.7), -60)


class AudioLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        patches = [mock.patch.object(clipper, "AUDIO_DIR", self.dir), mock.patch.object(clipper, "AUDIO_DIRS", [self.dir]),
                   mock.patch.object(clipper, "audio_registry", {})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_the_library_lists_songs_and_effects_by_length(self):
        tone(str(self.dir / "whoosh.wav"), 1)
        tone(str(self.dir / "theme.wav"), 20)
        (self.dir / "notes.txt").write_text("not audio")
        items = {i["name"]: i for i in clipper.scan_audio()}
        self.assertEqual({k: v["kind"] for k, v in items.items()}, {"whoosh": "sfx", "theme": "song"})

    def test_uploads_only_take_audio_and_keep_names_free(self):
        self.assertIsNone(clipper.upload_target("clip.mp4", clipper.AUDIO_EXTS, self.dir))
        first = clipper.upload_target("Boom Hit.mp3", clipper.AUDIO_EXTS, self.dir)
        first.write_bytes(b"x")
        self.assertEqual(clipper.upload_target("Boom Hit.mp3", clipper.AUDIO_EXTS, self.dir).name, "Boom Hit-2.mp3")

    def test_the_project_sounds_resolve_to_library_files(self):
        tone(str(self.dir / "hit.wav"), 2)
        sound = clipper.scan_audio()[0]
        items = clipper.audio_mix_items({"audio": [{"file": sound["id"], "start": 3, "in": 0.5, "dur": 1, "volume": 0.8, "fadeIn": 0.2}]})
        self.assertEqual((items[0]["path"], items[0]["start"], items[0]["volume"], items[0]["fadein"]), (sound["path"], 3.0, 0.8, 0.2))

    def test_a_sound_missing_from_the_library_stops_the_render_with_a_clear_message(self):
        with self.assertRaises(ValueError) as err:
            clipper.audio_mix_items({"audio": [{"file": "0123456789ab", "dur": 1}]})
        self.assertIn("missing from the audio library", str(err.exception))


if __name__ == "__main__":
    unittest.main()


class AudioKindTests(unittest.TestCase):
    def test_a_wav_saved_as_mp3_is_served_and_named_as_a_wav(self):
        with tempfile.TemporaryDirectory() as d:
            real = Path(d) / "tone.wav"
            tone(str(real), 0.2)
            wrong = real.rename(Path(d) / "tone.mp3")
            self.assertEqual(clipper.audio_type(wrong), "audio/wav")
            self.assertEqual(clipper.audio_suffix(wrong.read_bytes()[:12]), ".wav")

    def test_an_mp3_keeps_its_type_and_unknown_bytes_use_the_extension(self):
        with tempfile.TemporaryDirectory() as d:
            mp3 = Path(d) / "tone.mp3"
            tone(str(mp3), 0.2)
            self.assertEqual(clipper.audio_type(mp3), "audio/mpeg")
            odd = Path(d) / "odd.ogg"
            odd.write_bytes(b"\x00" * 16)
            self.assertEqual(clipper.audio_type(odd), "audio/ogg")


class HookEmojiTests(unittest.TestCase):
    def test_an_emoji_in_the_hook_is_drawn_and_counts_as_one_letter_wide(self):
        from PIL import Image
        geo = make_short.card_geometry((1080, 1920), "bro got violated \U0001F480", "title", "9:16")
        self.assertEqual(geo["lines"], ["bro got violated \U0001F480"])
        self.assertEqual(make_short.hook_runs(geo["lines"][0])[-1], ("\U0001F480", True))
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "card.png"
            make_short.render_card(geo, "n", "h", None, str(dest))
            card = Image.open(dest).convert("RGB")
            x0 = int(make_short.PAD + make_short.line_width(geo["font"], "bro got violated "))
            y0 = geo["top"]
            patch = card.crop((x0, y0, x0 + geo["font"].size, y0 + geo["line_h"]))
            self.assertTrue(any(px != make_short.CARD_BG for px in patch.getdata()), "nothing drawn where the emoji goes")
