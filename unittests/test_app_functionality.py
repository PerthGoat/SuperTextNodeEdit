import configparser
import importlib.util
import os
from pathlib import Path
import tempfile
import threading
import tkinter as tk
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "__main__.py"

spec = importlib.util.spec_from_file_location("supertext_app", APP_PATH)
app = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(app)


class FakeClipboard:
    TEXT = 1
    UNITEXT = 13
    BITMAP = 0x8
    RTF_NO_OBJ = 49514

    def open_clipboard(self):
        pass

    def close_clipboard(self):
        pass

    def clear_clipboard(self):
        pass

    def get_clipboard(self):
        return None

    def set_clipboard(self, data, data_type):
        self.last_set = (data, data_type)


def make_config(path, node_dir):
    config = configparser.ConfigParser()
    config["constants"] = {
        "RTF_HEADER": r"{\rtf1\ansi\pard {\fonttbl\f0\fswiss Consolas;}\f0 ",
        "nodeDir": str(node_dir),
    }
    with open(path, "w", encoding="utf-8") as fi:
        config.write(fi)


def can_create_tk():
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        return True
    except tk.TclError:
        return False
    finally:
        if root is not None:
            root.destroy()


@unittest.skipUnless(can_create_tk(), "Tk display is not available")
class TestRTFWindowFunctionality(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.node_dir = self.root / "nodes"
        self.node_dir.mkdir()
        make_config(self.root / "rtfjournal.ini", self.node_dir)
        self.clipboard_patch = mock.patch.object(app, "Clipboard", FakeClipboard)
        self.clipboard_patch.start()
        self.window = app.RTFWindow(
            configFile=str(self.root / "rtfjournal.ini"),
            start_mainloop=False,
            start_worker=False,
        )
        self.window.window.withdraw()
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        self.clipboard_patch.stop()
        try:
            self.window.window.destroy()
        finally:
            self.tmp.cleanup()

    def write_node(self, relative_path, body):
        relative = Path(relative_path)
        node_folder = self.node_dir / relative
        node_folder.mkdir(parents=True, exist_ok=True)
        rtf_file = self.node_dir / relative.with_suffix(".rtf")
        rtf_file.parent.mkdir(parents=True, exist_ok=True)
        rtf_file.write_text(self.window.RTF_HEADER + body + "}", encoding="utf-8")
        return rtf_file

    def test_populate_node_tree_selects_first_node_and_builds_paths(self):
        self.write_node("alpha", "Alpha text")
        self.write_node(Path("alpha") / "beta", "Beta text")
        self.write_node("gamma", "Gamma text")

        self.window.populateNodeTree()

        root_items = self.window.tree.get_children()
        root_names = [self.window.tree.item(item)["text"] for item in root_items]
        self.assertEqual(["alpha", "gamma"], root_names)
        self.assertEqual(self.window.tree.item(self.window.selected_node)["text"], "alpha")

        self.window.tree.item(root_items[0], open=True)
        self.window.populateNodeTree(
            str(self.node_dir / "alpha") + os.sep,
            root_items[0],
        )
        child = self.window.tree.get_children(root_items[0])[0]
        self.assertEqual("alpha" + os.sep + "beta", self.window.get_node_path(child))

    def test_try_read_show_rtf_loads_selected_node_text(self):
        self.write_node("alpha", r"Hello{\par }World")

        self.window.populateNodeTree()
        self.window.tryReadShowRTF(None)

        self.assertEqual(str(self.node_dir / "alpha.rtf"), self.window.openFile)
        self.assertEqual("Hello\nWorld\n", self.window.text.get("1.0", "end"))

    def test_create_new_node_writes_folder_and_rtf_file(self):
        self.window.selected_node = ()

        self.window.createNewNode()

        self.assertTrue((self.node_dir / "newNode0").is_dir())
        new_file = self.node_dir / "newNode0.rtf"
        self.assertTrue(new_file.is_file())
        self.assertEqual(self.window.RTF_HEADER + "}", new_file.read_text())

    def test_rename_node_refreshes_tree_and_reselects_renamed_node(self):
        self.write_node("newNode33", "Node text")
        self.window.populateNodeTree()
        node = self.window.find_self("newNode33")

        self.window.renameFileAndDir(node, "newNode33", "renamedNode")

        self.assertFalse((self.node_dir / "newNode33").exists())
        self.assertFalse((self.node_dir / "newNode33.rtf").exists())
        self.assertTrue((self.node_dir / "renamedNode").is_dir())
        self.assertTrue((self.node_dir / "renamedNode.rtf").is_file())
        self.assertEqual("renamedNode", self.window.tree.item(self.window.selected_node)["text"])
        self.assertEqual("renamedNode", self.window.get_node_path(self.window.selected_node))

    def test_rename_rejects_paths_outside_node_directory(self):
        self.write_node("newNode33", "Node text")
        outside_dir = self.root / "outside"
        outside_dir.mkdir()
        self.window.populateNodeTree()
        node = self.window.find_self("newNode33")

        with mock.patch.object(app.messagebox, "showerror") as showerror:
            self.window.renameFileAndDir(node, "newNode33", str(outside_dir / "escapedNode"))

        showerror.assert_called_once()
        self.assertTrue((self.node_dir / "newNode33").is_dir())
        self.assertTrue((self.node_dir / "newNode33.rtf").is_file())
        self.assertFalse((outside_dir / "escapedNode").exists())
        self.assertFalse((outside_dir / "escapedNode.rtf").exists())

    def test_action_queue_drains_on_calling_thread_without_reschedule_when_disabled(self):
        calling_thread = threading.get_ident()
        seen_threads = []

        self.window.actionQueue.put(
            app.PrioritizedItem(
                0,
                lambda: seen_threads.append(threading.get_ident()),
                "captureThread",
            )
        )

        with mock.patch("builtins.print"), mock.patch.object(self.window, "LogWithDateTime"):
            self.window.processActionQueueItem()

        self.assertEqual([calling_thread], seen_threads)
        self.assertIsNone(self.window._queue_after_id)

    def test_convert_to_rtf_escapes_text_newlines_and_unicode(self):
        self.window.openFile = str(self.node_dir / "scratch.rtf")
        self.window.text.insert("1.0", "slash \\ brace { close }")
        self.window.text.insert("end", "\nSnowman: \u2603")

        rtf = self.window.convertToRTF("1.0", "end")

        self.assertIn(r"slash \\ brace \{ close \}", rtf)
        self.assertIn(r"{\par }Snowman: \u9731?", rtf)
        self.assertTrue(rtf.startswith(self.window.RTF_HEADER))
        self.assertTrue(rtf.endswith("}"))

    def test_convert_to_rtf_exports_selected_text_formatting(self):
        self.window.openFile = str(self.node_dir / "scratch.rtf")
        self.window.text.insert("1.0", "Hello World")
        self.window.text.tag_add("sel", "1.6", "1.11")

        self.window.font_family_var.set("Arial")
        self.window.applySelectedFontFamily()
        self.window.font_size_var.set(18)
        self.window.applySelectedFontSize()
        self.window.applyStylePropertyToSelection("color", "#ff0000")
        self.window.toggleBoldForSelection()
        self.window.toggleItalicForSelection()

        rtf = self.window.convertToRTF("1.0", "end")

        self.assertIn(r"{\fonttbl{\f0\fswiss Consolas;}{\f1\fswiss Arial;}}", rtf)
        self.assertIn(r"{\colortbl ;\red255\green0\blue0;}", rtf)
        self.assertIn(r"Hello ", rtf)
        self.assertIn(r"{\f1\fs36\cf1\b\i World}", rtf)

    def test_toolbar_size_updates_from_current_selection(self):
        self.window.text.insert("1.0", "Small Big")
        self.window.applyStylePropertyToRange("1.0", "1.5", "font_size", 10)
        self.window.applyStylePropertyToRange("1.6", "1.9", "font_size", 24)

        self.window.text.tag_add("sel", "1.0", "1.5")
        self.window.updateToolbarStyleFromSelection()
        self.assertEqual(10, self.window.font_size_var.get())

        self.window.text.tag_remove("sel", "1.0", "1.5")
        self.window.text.tag_add("sel", "1.6", "1.9")
        self.window.updateToolbarStyleFromSelection()
        self.assertEqual(24, self.window.font_size_var.get())

    def test_display_nested_rtf_structure_imports_text_formatting(self):
        rtf_text = (
            r"{\rtf1\ansi\pard "
            r"{\fonttbl{\f0\fswiss Consolas;}{\f1\fswiss Arial;}}"
            r"{\colortbl ;\red255\green0\blue0;}"
            r"\f0\fs24 Plain {\f1\fs32\cf1\b\i Fancy}}"
        )

        parsed = app.RTFParser(rtf_text).parseme()
        self.assertTrue(self.window.isSupportedRTF(parsed))

        self.window.displayNestedRTFStructure(parsed)

        self.assertEqual("Plain Fancy\n", self.window.text.get("1.0", "end"))
        fancy_style = self.window.getTextStyleAt("1.7")
        self.assertEqual("Arial", fancy_style["font_family"])
        self.assertEqual(16, fancy_style["font_size"])
        self.assertEqual("#ff0000", fancy_style["color"])
        self.assertTrue(fancy_style["bold"])
        self.assertTrue(fancy_style["italic"])

    def test_display_nested_rtf_structure_only_decodes_actual_picture_group(self):
        rtf_text = (
            r"{\rtf1\ansi\pard {\fonttbl{\f0\fswiss Consolas;}}\f0 "
            r"Prefix {\pict\pngblip\picw1\pich1 00} Suffix}"
        )

        parsed = app.RTFParser(rtf_text).parseme()

        with mock.patch("builtins.print") as print_mock:
            self.window.displayNestedRTFStructure(parsed)

        self.assertEqual("Prefix  Suffix\n", self.window.text.get("1.0", "end"))
        self.assertTrue(print_mock.called)
        printed = " ".join(str(arg) for call in print_mock.call_args_list for arg in call.args)
        self.assertNotIn("non-hexadecimal", printed)


if __name__ == "__main__":
    unittest.main()
