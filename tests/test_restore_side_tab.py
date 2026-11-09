"""The left panel is the Sources list, in either station. It once also held an Effects grid that the Short station's rail replaced;
that grid showed up in the Clips station after opening a project whose saved session was in the other station."""
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "scripts" / "clipper_ui" / "app.js"


class RestoreSideTab(unittest.TestCase):
    def test_restoring_into_another_station_shows_the_sources_list(self):
        restore = APP.read_text().split("async function restoreEditorSession()", 1)[1].split("\n}\n", 1)[0]
        switch = restore.split("if (state.mode !== mode) {", 1)[1].split("\n  }\n", 1)[0]
        self.assertIn('setSideTab("media")', switch)

    def test_there_is_no_effects_grid_in_the_sidebar_any_more(self):
        ui = Path(APP).parent
        for name in ("index.html", "app.js", "style.css"):
            text = (ui / name).read_text()
            for gone in ("tabFx", "fxPanel", "fxGrid", "renderFx"):
                self.assertNotIn(gone, text, f"{gone} in {name}")


if __name__ == "__main__":
    unittest.main()
