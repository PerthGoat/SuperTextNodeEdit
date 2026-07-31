import base64
import io
import json
import struct
import unittest
from unittest import mock

from PIL import Image

from src.os_specific import Clipboard, ClipboardError


class CompletedScript:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class TestMacOSClipboard(unittest.TestCase):
    def setUp(self):
        platform_patch = mock.patch("src.os_specific.sys.platform", "darwin")
        platform_patch.start()
        self.addCleanup(platform_patch.stop)

    def test_macos_is_selected_before_generic_posix(self):
        clipboard = Clipboard()

        self.assertEqual("utf-8", clipboard.text_encoding)
        self.assertEqual(b"Snowman: \xe2\x98\x83", clipboard.encode_text("Snowman: \u2603"))

    def test_copy_queues_plain_and_rich_text_in_one_pasteboard_write(self):
        clipboard = Clipboard()
        rtf = br"{\rtf1\ansi Rich text}"

        with mock.patch(
            "src.os_specific.subprocess.run",
            return_value=CompletedScript(),
        ) as run:
            clipboard.open_clipboard()
            clipboard.clear_clipboard()
            clipboard.set_clipboard("Hello \u2603".encode("utf-16-le"), clipboard.UNITEXT)
            clipboard.set_clipboard(rtf, clipboard.RTF_NO_OBJ)
            clipboard.close_clipboard()

        payload = json.loads(run.call_args.kwargs["input"])
        items = {
            item["type"]: base64.b64decode(item["data"])
            for item in payload["items"]
        }
        self.assertEqual([], payload["files"])
        self.assertEqual("Hello \u2603".encode(), items["public.utf8-plain-text"])
        self.assertEqual(rtf, items["public.rtf"])

    def test_bitmap_is_converted_from_windows_dib_to_macos_tiff(self):
        clipboard = Clipboard()
        dib = io.BytesIO()
        Image.new("RGB", (4, 3), "blue").save(dib, "DIB")

        with mock.patch(
            "src.os_specific.subprocess.run",
            return_value=CompletedScript(),
        ) as run:
            clipboard.open_clipboard()
            clipboard.clear_clipboard()
            clipboard.set_clipboard(dib.getvalue(), clipboard.BITMAP)
            clipboard.close_clipboard()

        payload = json.loads(run.call_args.kwargs["input"])
        item = payload["items"][0]
        self.assertEqual("public.tiff", item["type"])
        with Image.open(io.BytesIO(base64.b64decode(item["data"]))) as copied:
            self.assertEqual("TIFF", copied.format)
            self.assertEqual((4, 3), copied.size)

    def test_windows_file_drop_payload_becomes_native_file_urls(self):
        clipboard = Clipboard()
        paths = ["/tmp/first.txt", "/tmp/second \u2603.bin"]
        names = ("\0".join(paths) + "\0\0").encode("utf-16-le")
        drop = struct.pack("<IiiII", 20, 0, 0, 0, 1) + names

        with mock.patch(
            "src.os_specific.subprocess.run",
            return_value=CompletedScript(),
        ) as run:
            clipboard.open_clipboard()
            clipboard.clear_clipboard()
            clipboard.set_clipboard(drop, clipboard.FILES)
            clipboard.close_clipboard()

        payload = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(paths, payload["files"])
        self.assertEqual([], payload["items"])
        self.assertIsNone(clipboard.register_format("Preferred DropEffect"))
        self.assertIsNone(clipboard.register_format("FileNameW"))

    def test_windows_html_header_is_removed_for_public_html(self):
        clipboard = Clipboard()
        document = b"<html><body><!--StartFragment--><b>Hi</b><!--EndFragment--></body></html>"
        template = b"Version:0.9\r\nStartHTML:%010d\r\nEndHTML:%010d\r\n"
        placeholder = template % (0, 0)
        payload = template % (len(placeholder), len(placeholder) + len(document))
        payload += document

        with mock.patch(
            "src.os_specific.subprocess.run",
            return_value=CompletedScript(),
        ) as run:
            clipboard.open_clipboard()
            clipboard.clear_clipboard()
            html_type = clipboard.register_format("HTML Format")
            clipboard.set_clipboard(payload, html_type)
            clipboard.close_clipboard()

        written = json.loads(run.call_args.kwargs["input"])["items"][0]
        self.assertEqual("public.html", written["type"])
        self.assertEqual(document, base64.b64decode(written["data"]))

    def test_rtf_and_file_urls_are_read_from_native_pasteboard(self):
        clipboard = Clipboard()
        rtf = br"{\rtf1\ansi Pasted}"
        responses = [
            CompletedScript(stdout=base64.b64encode(rtf).decode()),
            CompletedScript(stdout=json.dumps(["/tmp/copied.txt"])),
        ]

        with mock.patch("src.os_specific.subprocess.run", side_effect=responses):
            clipboard.open_clipboard()
            self.assertEqual(rtf.decode(), clipboard.get_clipboard())
            self.assertEqual(["/tmp/copied.txt"], clipboard.get_file_paths())
            clipboard.close_clipboard()

    def test_native_script_errors_are_reported(self):
        clipboard = Clipboard()

        with mock.patch(
            "src.os_specific.subprocess.run",
            return_value=CompletedScript(stderr="pasteboard unavailable", returncode=1),
        ):
            clipboard.open_clipboard()
            with self.assertRaisesRegex(ClipboardError, "pasteboard unavailable"):
                clipboard.get_clipboard()


if __name__ == "__main__":
    unittest.main()
