import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "__main__.py"
spec = importlib.util.spec_from_file_location("supertext_platform_ui", APP_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Could not load application module from {APP_PATH}")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class FakeWidget:
    def __init__(self):
        self.bindings = []

    def bind(self, sequence, callback, add=None):
        self.bindings.append((sequence, callback, add))


class TestPlatformUIHelpers(unittest.TestCase):
    def make_window(self, is_macos=True):
        window = app.RTFWindow.__new__(app.RTFWindow)
        window.is_macos = is_macos
        window.primary_modifier = "Command" if is_macos else "Control"
        return window

    def test_macos_shortcut_uses_command(self):
        window = self.make_window()
        widget = FakeWidget()
        callback = mock.Mock()

        sequence = window.bindShortcut(widget, "s", callback, shift=True)

        self.assertEqual("<Command-Shift-s>", sequence)
        self.assertIn(("<Command-Shift-s>", callback, None), widget.bindings)

    def test_macos_context_menu_accepts_secondary_and_control_clicks(self):
        window = self.make_window()
        widget = FakeWidget()
        callback = mock.Mock()

        window.bindContextMenu(widget, callback)

        self.assertEqual(
            {"<Button-3>", "<Button-2>", "<Control-Button-1>"},
            {sequence for sequence, _, _ in widget.bindings},
        )

    def test_command_modified_key_is_not_inserted_as_text(self):
        window = self.make_window()

        event = SimpleNamespace(state=0x0008, keysym="b", char="b")

        self.assertIsNone(window.typedCharacterFromEvent(event))

    def test_macos_opens_targets_with_open_command(self):
        window = self.make_window()

        with (
            mock.patch.object(app.os, "name", "posix"),
            mock.patch.object(app.sys, "platform", "darwin"),
            mock.patch.object(app.subprocess, "Popen") as popen,
        ):
            window.openWithDefaultApplication("/tmp/a file.txt")

        popen.assert_called_once_with(["open", "/tmp/a file.txt"])


if __name__ == "__main__":
    unittest.main()
