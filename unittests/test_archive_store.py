import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from src.archive_store import ArchiveConflictError, NoteArchiveStore
from src.search_index import NoteSearchIndex


RTF_HEADER = r"{\rtf1\ansi\pard {\fonttbl\f0\fswiss Consolas;}\f0 "


class TestNoteArchiveStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = NoteArchiveStore(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def write_note(self, relative_path, body):
        relative_path = Path(relative_path)
        folder = self.root / relative_path
        folder.mkdir(parents=True, exist_ok=True)
        note = self.root / relative_path.with_suffix(".rtf")
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(RTF_HEADER + body + "}", encoding="utf-8")
        return note

    def test_archive_compresses_subtree_searches_it_and_restores_it(self):
        parent_note = self.write_note("projects", "Quarterly overview")
        child_note = self.write_note(
            Path("projects") / "roadmap",
            "Launch the searchable starship in October",
        )
        companion = self.root / "projects" / "supporting.bin"
        companion.write_bytes(b"\x00\x01supporting-data")

        record = self.store.archive("projects")

        self.assertFalse(parent_note.exists())
        self.assertFalse((self.root / "projects").exists())
        archives = self.store.list_archives()
        self.assertEqual([record], archives)
        self.assertEqual(2, record.note_count)
        archive_path = Path(self.store.archive_dir) / f"{record.archive_id}.zip"
        self.assertTrue(zipfile.is_zipfile(archive_path))
        self.assertLess(record.compressed_size, 4096)

        results = self.store.search("STARSHIP")
        self.assertEqual(
            [os.path.join("projects", "roadmap")],
            [result.note_path for result in results],
        )
        self.assertIn("searchable starship", results[0].snippet)
        self.assertEqual(record.archive_id, results[0].archive_id)

        restored_path = self.store.restore(record.archive_id)

        self.assertEqual("projects", restored_path)
        self.assertEqual(
            RTF_HEADER + "Quarterly overview}",
            parent_note.read_text(encoding="utf-8"),
        )
        self.assertEqual(
            RTF_HEADER + "Launch the searchable starship in October}",
            child_note.read_text(encoding="utf-8"),
        )
        self.assertEqual(b"\x00\x01supporting-data", companion.read_bytes())
        self.assertEqual([], self.store.list_archives())

    def test_empty_search_lists_each_archived_note(self):
        self.write_note("parent", "Parent")
        self.write_note(Path("parent") / "child", "Child")
        self.store.archive("parent")

        results = self.store.search("")

        self.assertEqual(
            ["parent", os.path.join("parent", "child")],
            sorted(result.note_path for result in results),
        )

    def test_restore_refuses_to_overwrite_an_existing_node(self):
        self.write_note("alpha", "Archived version")
        record = self.store.archive("alpha")
        replacement = self.write_note("alpha", "Active replacement")

        with self.assertRaises(ArchiveConflictError):
            self.store.restore(record.archive_id)

        self.assertEqual(
            RTF_HEADER + "Active replacement}",
            replacement.read_text(encoding="utf-8"),
        )
        self.assertEqual(1, len(self.store.list_archives()))

    def test_active_search_index_does_not_index_archived_files(self):
        self.write_note("alpha", "Phrase only in archived note")
        index = NoteSearchIndex(self.root)
        self.store.archive("alpha")

        _stats, results = index.refresh_and_search("archived note")

        self.assertEqual([], results)


if __name__ == "__main__":
    unittest.main()
