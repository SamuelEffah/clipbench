import unittest
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "scripts" / "clipper_ui"


class HookEditInPreviewTests(unittest.TestCase):
    def test_hook_in_the_preview_is_editable_and_saved_to_the_project(self):
        app = (UI / "app.js").read_text()
        self.assertIn('contentEditable = spec.hookPx ? "plaintext-only" : "false"', app)
        self.assertIn('state.project = {...state.project, hook: text};\n      changed(true, "hook");', app)

    def test_relayout_does_not_overwrite_the_hook_being_typed(self):
        app = (UI / "app.js").read_text()
        self.assertIn('if (document.activeElement !== $("cHook")) $("cHook").textContent', app)

    def test_shortcuts_stay_out_of_the_hook(self):
        app = (UI / "app.js").read_text()
        self.assertIn("e.target.isContentEditable", app)

    def test_empty_hook_has_a_click_target(self):
        css = (UI / "style.css").read_text()
        self.assertIn('#cHook:empty::before{content:"Add a hook"', css)


if __name__ == "__main__":
    unittest.main()
