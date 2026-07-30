import configparser
import importlib.util
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest import mock

from PIL import ImageChops, ImageGrab


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "__main__.py"
ARTIFACT_DIR = ROOT / "unittests" / "artifacts" / "visual"

spec = importlib.util.spec_from_file_location("supertext_app_visual", APP_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Could not load application module from {APP_PATH}")
app = importlib.util.module_from_spec(spec)
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
        pass


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
class TestVisualSmoke(unittest.TestCase):
    def test_main_window_layout_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node_dir = root / "nodes"
            node_dir.mkdir()
            make_config(root / "rtfjournal.ini", node_dir)

            with mock.patch.object(app, "Clipboard", FakeClipboard):
                window = app.RTFWindow(
                    configFile=str(root / "rtfjournal.ini"),
                    start_mainloop=False,
                    start_worker=False,
                )

            try:
                window.window.update_idletasks()
                self.assertTrue(window.window.title().startswith("SuperText"))
                self.assertGreaterEqual(window.window.winfo_width(), 1200)
                self.assertGreaterEqual(window.window.winfo_height(), 650)
                self.assertEqual(window.tree.column("#0")["anchor"], "w")
                self.assertEqual(window.tree.heading("#0")["text"], "Nodes")
                self.assertEqual(window.text.index("end"), "2.0")
            finally:
                window.window.destroy()

    def test_main_window_renders_non_blank_screenshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node_dir = root / "nodes"
            node_dir.mkdir()
            make_config(root / "rtfjournal.ini", node_dir)

            with mock.patch.object(app, "Clipboard", FakeClipboard):
                window = app.RTFWindow(
                    configFile=str(root / "rtfjournal.ini"),
                    start_mainloop=False,
                    start_worker=False,
                )

            try:
                window.window.deiconify()
                window.window.update_idletasks()
                window.window.update()

                x = window.window.winfo_rootx()
                y = window.window.winfo_rooty()
                width = window.window.winfo_width()
                height = window.window.winfo_height()
                self.assertGreaterEqual(width, 1000)
                self.assertGreaterEqual(height, 600)

                try:
                    screenshot = ImageGrab.grab(bbox=(x, y, x + width, y + height))
                except OSError as exc:
                    self.skipTest(f"Could not capture desktop screenshot: {exc}")

                ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
                screenshot_path = ARTIFACT_DIR / "main_window.png"
                screenshot.save(screenshot_path)

                baseline = screenshot.crop((0, 0, 1, 1)).resize(
                    screenshot.size
                )
                self.assertIsNotNone(ImageChops.difference(screenshot, baseline).getbbox())
            finally:
                window.window.destroy()


if __name__ == "__main__":
    unittest.main()
