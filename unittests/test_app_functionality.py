import configparser
import importlib.util
import os
from pathlib import Path
import tempfile
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

    def test_convert_to_rtf_escapes_text_newlines_and_unicode(self):
        self.window.openFile = str(self.node_dir / "scratch.rtf")
        self.window.text.insert("1.0", "slash \\ brace { close }")
        self.window.text.insert("end", "\nSnowman: \u2603")

        rtf = self.window.convertToRTF("1.0", "end")

        self.assertIn(r"slash \\ brace \{ close \}", rtf)
        self.assertIn(r"{\par }Snowman: \u9731?", rtf)
        self.assertTrue(rtf.startswith(self.window.RTF_HEADER))
        self.assertTrue(rtf.endswith("}"))


if __name__ == "__main__":
    unittest.main()
