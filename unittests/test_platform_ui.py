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


class FakeWindow(FakeWidget):
    def __init__(self):
        super().__init__()
        self.options = {"menu": ""}
        self.commands = {}
        self.tk = self

    def __str__(self):
        return "."

    def cget(self, option):
        return self.options.get(option, "")

    def configure(self, **options):
        self.options.update(options)

    config = configure

    def bind_all(self, sequence, callback, add=None):
        self.bind(sequence, callback, add)

    def createcommand(self, name, callback):
        self.commands[name] = callback


class RecordingMenu:
    counter = 0

    def __init__(self, parent, **options):
        type(self).counter += 1
        self.parent = parent
        self.options = options
        self.entries = []
        name = options.get("name", f"menu{self.counter}")
        parent_path = str(parent).rstrip(".")
        self.path = f"{parent_path}.{name}" if parent_path else f".{name}"

    def __str__(self):
        return self.path

    def _add(self, kind, **options):
        self.entries.append((kind, options))

    def add_command(self, **options):
        self._add("command", **options)

    def add_checkbutton(self, **options):
        self._add("checkbutton", **options)

    def add_radiobutton(self, **options):
        self._add("radiobutton", **options)

    def add_cascade(self, **options):
        self._add("cascade", **options)

    def add_separator(self):
        self._add("separator")


class RecordingLayoutWidget:
    instances = []

    def __init__(self, parent, **options):
        self.parent = parent
        self.options = options
        self.pack_calls = []
        type(self).instances.append(self)

    def pack(self, **options):
        self.pack_calls.append(options)


class RecordingFrame(RecordingLayoutWidget):
    instances = []


class RecordingMenubutton(RecordingLayoutWidget):
    instances = []


class RecordingSeparator(RecordingLayoutWidget):
    instances = []


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

    def test_macos_menu_bar_has_required_aqua_special_menus_before_attach(self):
        window = self.make_window()
        window.window = FakeWindow()
        window.primary_accelerator = "Command"
        window.alternate_accelerator = "Option"
        window.alternate_modifier = "Option"
        window.wrap_text_var = object()
        window.font_size_var = object()
        window.format_painter_menu_var = object()
        window.bold_menu_var = object()
        window.italic_menu_var = object()
        window.underline_menu_var = object()
        window.center_menu_var = object()

        with (
            mock.patch.object(app.tk, "Menu", RecordingMenu),
            mock.patch.object(window, "createInlineMenuBar") as create_inline,
        ):
            window.createMenuBar()

        self.assertEqual("menubar", window.menu_bar.options["name"])
        self.assertEqual("apple", window.menus["application"].options["name"])
        self.assertEqual("window", window.menus["window"].options["name"])
        self.assertEqual("help", window.menus["help"].options["name"])
        first_entry = window.menu_bar.entries[0]
        self.assertEqual("cascade", first_entry[0])
        self.assertIs(window.menus["application"], first_entry[1]["menu"])
        self.assertIs(window.menu_bar, window.window.options["menu"])
        self.assertEqual(window.closeWindow, window.window.commands["tk::mac::Quit"])
        create_inline.assert_called_once_with()

    def test_macos_inline_menu_bar_exposes_all_application_menus(self):
        window = self.make_window()
        window.window = FakeWindow()
        menu_names = (
            "file",
            "edit",
            "view",
            "nodes",
            "insert",
            "format",
            "window",
            "help",
        )
        window.menus = {name: object() for name in menu_names}
        RecordingFrame.instances.clear()
        RecordingMenubutton.instances.clear()
        RecordingSeparator.instances.clear()

        with (
            mock.patch.object(app.ttk, "Frame", RecordingFrame),
            mock.patch.object(app.ttk, "Menubutton", RecordingMenubutton),
            mock.patch.object(app.ttk, "Separator", RecordingSeparator),
        ):
            window.createInlineMenuBar()

        self.assertEqual(
            ["File", "Edit", "View", "Nodes", "Insert", "Format", "Window", "Help"],
            [button.options["text"] for button in RecordingMenubutton.instances],
        )
        self.assertEqual(set(menu_names), set(window.inline_menu_buttons))
        self.assertEqual(
            [{"side": "top", "fill": "x"}],
            window.inline_menu_bar.pack_calls,
        )

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
