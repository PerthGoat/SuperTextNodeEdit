import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from src.search_index import NoteSearchIndex, rtf_to_plain_text


RTF_HEADER = r"{\rtf1\ansi\pard {\fonttbl\f0\fswiss Consolas;}\f0 "


class TestNoteSearchIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.index = NoteSearchIndex(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def write_note(self, relative_path, body):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(RTF_HEADER + body + "}", encoding="utf-8")
        return path

    def test_plain_text_ignores_metadata_images_and_attachments(self):
        rtf = (
            RTF_HEADER
            + r"Before{\par }After "
            + r"{\pict\pngblip 414243} "
            + r"{\supertextfile{\supertextfilename 666f6f}"
            + r"{\supertextdata 736563726574}}"
            + r"{\supertextlink"
            + r"{\*\supertextlinktype 75726c}"
            + r"{\*\supertexttarget 68747470733a2f2f7365637265742e6578616d706c65}"
            + r"{\supertextdisplay Visible link}}"
            + "}"
        )

        text = rtf_to_plain_text(rtf)

        self.assertIn("Before\nAfter", text)
        self.assertNotIn("Consolas", text)
        self.assertNotIn("414243", text)
        self.assertNotIn("736563726574", text)
        self.assertIn("Visible link", text)
        self.assertNotIn("68747470733a", text)

    def test_search_finds_case_insensitive_substrings_in_nested_notes(self):
        self.write_note("alpha.rtf", "A searchable HayStack value")
        self.write_note(Path("parent") / "child.rtf", "Needlework")
        self.write_note("miss.rtf", "Nothing relevant")

        stats, results = self.index.refresh_and_search("HAYstack")

        self.assertEqual(3, stats["updated"])
        self.assertEqual(["alpha"], [result.path for result in results])
        self.assertIn("searchable HayStack", results[0].snippet)

        results = self.index.search("needle")
        self.assertEqual(
            [os.path.join("parent", "child")],
            [result.path for result in results],
        )

    def test_refresh_only_reparses_changed_notes_and_removes_deleted_notes(self):
        first = self.write_note("first.rtf", "First uncommon phrase")
        second = self.write_note("second.rtf", "Second uncommon phrase")
        self.index.refresh()

        with mock.patch.object(
            self.index,
            "_read_rtf",
            wraps=self.index._read_rtf,
        ) as read_mock:
            stats = self.index.refresh()

        self.assertEqual({"updated": 0, "removed": 0}, stats)
        read_mock.assert_not_called()

        first.unlink()
        second.write_text(RTF_HEADER + "Changed unique value}", encoding="utf-8")
        stats = self.index.refresh()
        self.assertEqual({"updated": 1, "removed": 1}, stats)
        self.assertEqual([], self.index.search("First uncommon"))
        self.assertEqual(["second"], [r.path for r in self.index.search("unique")])

    def test_short_queries_are_supported(self):
        self.write_note("alpha.rtf", "A xylophone")
        self.write_note("beta.rtf", "Nothing matching")
        self.index.refresh()

        with mock.patch.object(
            self.index,
            "_read_rtf",
            wraps=self.index._read_rtf,
        ) as read_mock:
            results = self.index.search("x")

        self.assertEqual(["alpha"], [result.path for result in results])
        self.assertEqual(1, read_mock.call_count)


if __name__ == "__main__":
    unittest.main()
