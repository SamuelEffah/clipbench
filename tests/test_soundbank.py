import json
import unittest
from unittest import mock

from scripts import soundbank

GOOD = "b5c858c4-0dde-498a-8b1d-ce56af8575c6.mp3"


class BrowseTests(unittest.TestCase):
    def reply(self, data):
        return mock.patch.object(soundbank, "_get", return_value=json.dumps(data).encode())

    def test_lists_new_sounds_without_a_query(self):
        with self.reply({"total": 9, "data": [{"id": 1, "name": "VINE BOOM", "fileName": GOOD}]}) as get:
            out = soundbank.browse("", 2)
        self.assertIn("/memes/new?page=2&pageSize=40", get.call_args[0][0])
        self.assertEqual(out["sounds"], [{"id": 1, "name": "Vine Boom", "file": GOOD}])
        self.assertEqual(out["total"], 9)

    def test_searches_with_an_encoded_query(self):
        with self.reply({"total": 0, "data": []}) as get:
            soundbank.browse("vine boom&x", 1)
        self.assertIn("/memes/search?", get.call_args[0][0])
        self.assertIn("q=vine+boom%26x", get.call_args[0][0])

    def test_drops_entries_with_unexpected_file_names(self):
        with self.reply({"total": 2, "data": [{"id": 1, "name": "a", "fileName": "../x.mp3"}, {"id": 2, "name": "b", "fileName": GOOD}]}):
            self.assertEqual([s["id"] for s in soundbank.browse()["sounds"]], [2])


class FetchTests(unittest.TestCase):
    def test_rejects_names_the_site_would_not_issue(self):
        for bad in ("", "x.mp3", "../" + GOOD, GOOD + "?x=1"):
            with self.assertRaises(ValueError):
                soundbank.fetch(bad)

    def test_returns_the_bytes(self):
        with mock.patch.object(soundbank, "_get", return_value=b"ID3") as get:
            self.assertEqual(soundbank.fetch(GOOD), b"ID3")
        self.assertIn("upload/download?id=" + GOOD, get.call_args[0][0])

    def test_empty_download_is_an_error(self):
        with mock.patch.object(soundbank, "_get", return_value=b""):
            with self.assertRaises(ValueError):
                soundbank.fetch(GOOD)


if __name__ == "__main__":
    unittest.main()


class ImportTests(unittest.TestCase):
    def test_import_saves_into_the_audio_folder_and_refuses_bad_names(self):
        import tempfile
        from pathlib import Path
        from scripts import clipper
        with tempfile.TemporaryDirectory() as d:
            handler = mock.Mock()
            with mock.patch.object(clipper, "AUDIO_DIR", Path(d)), mock.patch.object(clipper.soundbank, "_get", return_value=b"ID3"):
                clipper.Handler.import_sound(handler, {"file": GOOD, "name": "Vine Boom"})
                self.assertEqual((Path(d) / "Vine Boom.mp3").read_bytes(), b"ID3")
                clipper.Handler.import_sound(handler, {"file": "../evil.mp3", "name": "x"})
            self.assertEqual(handler.send_json.call_args[0][1], 400)
