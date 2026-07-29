import configparser
import hashlib
import importlib.util
import os
import struct
from pathlib import Path
from types import SimpleNamespace
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
    FILES = 15

    def __init__(self):
        self.set_calls = []

    def open_clipboard(self):
        pass

    def close_clipboard(self):
        pass

    def clear_clipboard(self):
        pass

    def get_clipboard(self):
        return None

    def get_file_paths(self):
        return []

    def register_format(self, name):
        self.registered_formats = getattr(self, 'registered_formats', [])
        self.registered_formats.append(name)
        return {'Preferred DropEffect': 0xC123, 'FileNameW': 0xC124}[name]

    def set_clipboard(self, data, data_type):
        self.last_set = (data, data_type)
        self.set_calls.append((data, data_type))


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

    def test_single_click_previews_another_note_in_the_only_open_tab(self):
        self.write_node("alpha", "Alpha text")
        self.write_node("beta", "Beta text")
        self.window.populateNodeTree()
        self.window.tryReadShowRTF(None)
        beta = self.window.find_self("beta")

        self.window.previewNodeInFirstTab(beta)

        self.assertEqual((beta,), self.window.tree.selection())
        self.assertEqual(str(self.node_dir / "beta.rtf"), self.window.openFile)
        self.assertEqual("Beta text", self.window.text.get("1.0", "end-1c"))
        self.assertEqual(1, len(self.window.editor_tabs.tabs()))

    def test_canceling_single_click_preview_keeps_unsaved_note_open(self):
        self.write_node("alpha", "Alpha text")
        self.write_node("beta", "Beta text")
        self.window.populateNodeTree()
        self.window.tryReadShowRTF(None)
        self.window.text.insert("end-1c", " changed")
        beta = self.window.find_self("beta")

        with mock.patch.object(app.messagebox, "askyesnocancel", return_value=None):
            self.window.previewNodeInFirstTab(beta)

        self.assertEqual(str(self.node_dir / "alpha.rtf"), self.window.openFile)
        self.assertEqual("Alpha text changed", self.window.text.get("1.0", "end-1c"))
        self.assertEqual(1, len(self.window.editor_tabs.tabs()))
        self.assertEqual(
            "alpha",
            self.window.get_node_path(self.window.tree.selection()[0]),
        )

    def test_single_click_only_switches_first_tab_and_keeps_secondary_tab_pinned(self):
        self.write_node("alpha", "Alpha text")
        self.write_node("beta", "Beta text")
        self.write_node("gamma", "Gamma text")
        self.window.populateNodeTree()
        self.window.tryReadShowRTF(None)
        first_document = self.window.active_document

        beta = self.window.find_self("beta")
        event = SimpleNamespace(x=10, y=20)
        with mock.patch.object(self.window.tree, "identify", return_value=beta):
            self.window.openNodeFromTreeDoubleClick(event)
        pinned_document = self.window.active_document

        gamma = self.window.find_self("gamma")
        self.window.previewNodeInFirstTab(gamma)

        self.assertIs(first_document, self.window.active_document)
        self.assertEqual(str(self.node_dir / "gamma.rtf"), first_document.path)
        self.assertEqual(str(self.node_dir / "beta.rtf"), pinned_document.path)
        self.assertEqual(2, len(self.window.editor_tabs.tabs()))

        self.window.selectDocumentTab(pinned_document)
        self.assertEqual("Beta text", self.window.text.get("1.0", "end-1c"))

    def test_double_click_opens_a_separate_tab_without_toggling_selection(self):
        self.write_node("alpha", "Alpha text")
        self.write_node("beta", "Beta text")
        self.window.populateNodeTree()
        self.window.tryReadShowRTF(None)
        beta = self.window.find_self("beta")
        event = SimpleNamespace(x=10, y=20)

        with (
            mock.patch.object(self.window.tree, "identify", return_value=beta),
            mock.patch.object(
                self.window.tree.widget,
                "identify_element",
                return_value="Treeitem.text",
            ),
        ):
            self.window.scheduleNodePreview(event)
            self.assertIsNotNone(self.window.tree_single_click_after_id)
            result = self.window.openNodeFromTreeDoubleClick(event)
            self.assertIsNone(self.window.tree_single_click_after_id)
            self.window.scheduleNodePreview(event)

        self.assertEqual("break", result)
        self.assertIsNone(self.window.tree_single_click_after_id)
        self.assertEqual((beta,), self.window.tree.selection())
        self.assertEqual(str(self.node_dir / "beta.rtf"), self.window.openFile)
        self.assertEqual("Beta text", self.window.text.get("1.0", "end-1c"))
        self.assertEqual(2, len(self.window.editor_tabs.tabs()))

    def test_double_clicking_currently_selected_note_opens_duplicate_tab(self):
        self.write_node("alpha", "Alpha text")
        self.window.populateNodeTree()
        self.window.tryReadShowRTF(None)
        alpha = self.window.find_self("alpha")
        first_document = self.window.active_document
        self.window.text.insert("end-1c", " changed")
        event = SimpleNamespace(x=10, y=20)

        with mock.patch.object(self.window.tree, "identify", return_value=alpha):
            result = self.window.openNodeFromTreeDoubleClick(event)

        second_document = self.window.active_document
        self.assertEqual("break", result)
        self.assertIsNot(first_document, second_document)
        self.assertEqual(first_document.path, second_document.path)
        self.assertEqual(2, len(self.window.editor_tabs.tabs()))
        self.assertEqual("Alpha text changed", self.window.text.get("1.0", "end-1c"))
        self.assertTrue(second_document.dirty)
        self.assertTrue(
            self.window.editor_tabs.tab(second_document.tab_id, "text").startswith("* ")
        )

        self.window.closeDocumentTab(second_document.tab_id, force=True)
        self.assertEqual(
            first_document,
            self.window.open_documents_by_path[
                self.window.normalizedDocumentPath(first_document.path)
            ],
        )

    def test_editing_dedicated_tab_updates_same_node_in_preview_tab(self):
        self.write_node("alpha", "Alpha text")
        self.window.populateNodeTree()
        self.window.tryReadShowRTF(None)
        preview_document = self.window.active_document
        alpha = self.window.find_self("alpha")
        event = SimpleNamespace(x=10, y=20)

        with mock.patch.object(self.window.tree, "identify", return_value=alpha):
            self.window.openNodeFromTreeDoubleClick(event)

        dedicated_document = self.window.active_document
        self.window.text.insert("end-1c", " changed")
        self.window.selectDocumentTab(preview_document)

        self.assertEqual(
            "Alpha text changed",
            preview_document.text.get("1.0", "end-1c"),
        )
        self.assertTrue(preview_document.dirty)
        self.assertTrue(dedicated_document.dirty)
        self.assertTrue(
            self.window.editor_tabs.tab(preview_document.tab_id, "text").startswith("* ")
        )

    def test_opening_multiple_nodes_creates_tabs_and_preserves_unsaved_edits(self):
        self.write_node("alpha", "Alpha text")
        self.write_node("beta", "Beta text")
        self.window.populateNodeTree()
        self.window.tryReadShowRTF(None)
        alpha_document = self.window.active_document
        self.window.text.insert("end-1c", " changed")

        beta = self.window.find_self("beta")
        self.window.tree.selection_set(beta)
        self.window.tryReadShowRTF(None)

        self.assertEqual(2, len(self.window.editor_tabs.tabs()))
        self.assertEqual("Beta text", self.window.text.get("1.0", "end-1c"))

        alpha = self.window.find_self("alpha")
        self.window.tree.selection_set(alpha)
        self.window.tryReadShowRTF(None)

        self.assertIs(alpha_document, self.window.active_document)
        self.assertEqual(2, len(self.window.editor_tabs.tabs()))
        self.assertEqual("Alpha text changed", self.window.text.get("1.0", "end-1c"))

    def test_each_open_tab_keeps_its_own_undo_history(self):
        self.write_node("alpha", "Alpha text")
        self.write_node("beta", "Beta text")
        self.window.populateNodeTree()
        self.window.tryReadShowRTF(None)
        self.window.text.insert("end-1c", " changed")

        beta = self.window.find_self("beta")
        self.window.tree.selection_set(beta)
        self.window.tryReadShowRTF(None)
        self.window.text.insert("end-1c", " changed")

        alpha = self.window.find_self("alpha")
        self.window.tree.selection_set(alpha)
        self.window.tryReadShowRTF(None)
        self.window.undoDocument()

        self.assertEqual("Alpha text", self.window.text.get("1.0", "end-1c"))
        beta_document = self.window.open_documents_by_path[
            self.window.normalizedDocumentPath(str(self.node_dir / "beta.rtf"))
        ]
        self.window.selectDocumentTab(beta_document)
        self.assertEqual("Beta text changed", self.window.text.get("1.0", "end-1c"))

    def test_text_wrapping_is_configured_per_document(self):
        first_document = self.window.active_document

        self.window.wrap_text_var.set(False)
        self.window.applyTextWrappingFromMenu()

        self.assertFalse(first_document.wrap_text)
        self.assertEqual("none", first_document.text.widget.cget("wrap"))
        self.assertTrue(first_document.text.scrollx.grid_info())
        self.assertFalse(first_document.text.edit_modified())

        second_document = self.window.createDocumentTab()
        self.window.selectDocumentTab(second_document)

        self.assertTrue(second_document.wrap_text)
        self.assertTrue(self.window.wrap_text_var.get())
        self.assertEqual("word", second_document.text.widget.cget("wrap"))
        self.assertFalse(second_document.text.scrollx.grid_info())

        self.window.selectDocumentTab(first_document)

        self.assertFalse(self.window.wrap_text_var.get())
        self.assertEqual("none", self.window.text.widget.cget("wrap"))

    def test_text_wrapping_shortcut_toggles_only_active_document(self):
        first_document = self.window.active_document
        second_document = self.window.createDocumentTab()
        self.window.selectDocumentTab(second_document)

        self.assertEqual("break", self.window.toggleTextWrapping(SimpleNamespace()))

        self.assertFalse(second_document.wrap_text)
        self.assertTrue(first_document.wrap_text)
        self.assertFalse(self.window.wrap_text_var.get())

    def test_closing_a_modified_tab_can_discard_and_leaves_placeholder(self):
        note_file = self.write_node("alpha", "Alpha text")
        self.window.populateNodeTree()
        self.window.tryReadShowRTF(None)
        self.window.text.insert("end-1c", " changed")

        with mock.patch.object(app.messagebox, "askyesnocancel", return_value=False):
            self.window.closeCurrentTab()

        self.assertEqual(1, len(self.window.editor_tabs.tabs()))
        self.assertEqual("", self.window.openFile)
        saved_rtf = note_file.read_text(encoding="utf-8")
        self.assertIn("Alpha text", saved_rtf)
        self.assertNotIn("changed", saved_rtf)

    def test_renaming_an_open_node_updates_its_tab_path(self):
        self.write_node("alpha", "Alpha text")
        self.window.populateNodeTree()
        self.window.tryReadShowRTF(None)
        document = self.window.active_document
        node = self.window.find_self("alpha")

        self.window.renameFileAndDir(node, "alpha", "renamed")

        self.assertIs(document, self.window.active_document)
        self.assertEqual(str(self.node_dir / "renamed.rtf"), document.path)
        self.assertEqual("renamed", document.relative_path)
        self.assertEqual(document.path, self.window.openFile)
        self.assertEqual(
            "renamed",
            self.window.editor_tabs.tab(document.tab_id, "text"),
        )

    def test_search_result_opens_a_deep_lazily_loaded_node(self):
        self.write_node("alpha", "Alpha text")
        self.write_node(Path("alpha") / "beta", "Deep result text")
        self.window.populateNodeTree()

        selected = self.window.selectNodePath(os.path.join("alpha", "beta"))

        self.assertIsNotNone(selected)
        self.assertEqual(
            os.path.join("alpha", "beta"),
            self.window.get_node_path(selected),
        )
        self.assertEqual(
            str(self.node_dir / "alpha" / "beta.rtf"),
            self.window.openFile,
        )
        self.assertEqual(
            "Deep result text",
            self.window.text.get("1.0", "end-1c"),
        )

    def test_undo_and_redo_document_edits(self):
        self.window.text.edit_reset()
        self.window.text.insert("1.0", "new text")

        self.assertEqual("break", self.window.undoDocument())
        self.assertEqual("", self.window.text.get("1.0", "end-1c"))

        self.assertEqual("break", self.window.redoDocument())
        self.assertEqual("new text", self.window.text.get("1.0", "end-1c"))

    def test_loading_node_resets_undo_history(self):
        self.window.text.insert("1.0", "previous document")
        self.write_node("alpha", "Loaded text")

        self.window.populateNodeTree()
        self.window.tryReadShowRTF(None)
        self.window.undoDocument()

        self.assertEqual("Loaded text", self.window.text.get("1.0", "end-1c"))

    def test_create_new_node_writes_folder_and_rtf_file(self):
        self.window.selected_node = ()

        self.window.createNewNode()

        self.assertTrue((self.node_dir / "newNode0").is_dir())
        new_file = self.node_dir / "newNode0.rtf"
        self.assertTrue(new_file.is_file())
        self.assertEqual(self.window.RTF_HEADER + "}", new_file.read_text())

    def test_archive_selected_node_removes_subtree_and_creates_searchable_bundle(self):
        self.write_node("parent", "Parent text")
        self.write_node(Path("parent") / "child", "Archived child phrase")
        self.window.populateNodeTree()
        self.window.selected_node = self.window.find_self("parent")

        with (
            mock.patch.object(app.messagebox, "askyesno", return_value=True),
            mock.patch.object(app.messagebox, "showinfo"),
        ):
            result = self.window.archiveSelectedNode()

        self.assertEqual("break", result)
        self.assertFalse((self.node_dir / "parent.rtf").exists())
        self.assertFalse((self.node_dir / "parent").exists())
        matches = self.window.archive_store.search("child phrase")
        self.assertEqual(
            [os.path.join("parent", "child")],
            [match.note_path for match in matches],
        )
        self.assertEqual(1, len(self.window.archive_store.list_archives()))

    def test_node_context_menu_selects_right_clicked_node(self):
        self.write_node("alpha", "Alpha text")
        self.write_node("beta", "Beta text")
        self.window.populateNodeTree()
        beta = self.window.find_self("beta")
        event = SimpleNamespace(x=10, y=20, x_root=110, y_root=220)
        context_menu = mock.Mock()

        with mock.patch.object(self.window.tree, "identify", return_value=beta):
            self.window.node_context_menu = context_menu
            result = self.window.showNodeContextMenu(event)

        self.assertEqual("break", result)
        self.assertEqual(beta, self.window.selected_node)
        self.assertEqual((beta,), self.window.tree.selection())
        context_menu.tk_popup.assert_called_once_with(110, 220)
        context_menu.grab_release.assert_called_once_with()

    def test_text_context_menu_preserves_selection_clicked_inside_it(self):
        self.window.text.insert("1.0", "selected text")
        self.window.text.tag_add("sel", "1.0", "1.8")
        context_menu = mock.Mock()
        self.window.text_context_menu = context_menu
        event = SimpleNamespace(x=1, y=1, x_root=110, y_root=220)

        with mock.patch.object(self.window.text, "index", return_value="1.3"):
            result = self.window.showTextContextMenu(event)

        self.assertEqual("break", result)
        self.assertTrue(self.window.text.tag_ranges("sel"))
        context_menu.entryconfigure.assert_any_call("Cut", state="normal")
        context_menu.entryconfigure.assert_any_call("Copy", state="normal")
        context_menu.tk_popup.assert_called_once_with(110, 220)
        context_menu.grab_release.assert_called_once_with()

    def test_cut_text_selection_uses_rich_copy_then_deletes_selection(self):
        self.window.text.insert("1.0", "cut me")
        self.window.text.tag_add("sel", "1.0", "1.3")

        with mock.patch.object(self.window, "copyFromClipboard", return_value="break") as copy:
            result = self.window.cutTextSelection()

        self.assertEqual("break", result)
        copy.assert_called_once_with(None)
        self.assertEqual(" me", self.window.text.get("1.0", "end-1c"))

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

    def test_duplicate_node_copies_subtree_selects_copy_and_starts_rename(self):
        source_file = self.write_node("alpha", "Alpha text")
        child_file = self.write_node(Path("alpha") / "beta", "Beta text")
        self.write_node("alpha copy", "Existing copy")
        self.window.populateNodeTree()
        self.window.selected_node = self.window.find_self("alpha")

        with mock.patch.object(self.window, "renameNode", return_value="break") as rename:
            result = self.window.duplicateNode()

        duplicate_dir = self.node_dir / "alpha copy 2"
        duplicate_file = self.node_dir / "alpha copy 2.rtf"
        duplicate_child_file = duplicate_dir / "beta.rtf"
        self.assertEqual("break", result)
        self.assertTrue(duplicate_dir.is_dir())
        self.assertEqual(source_file.read_bytes(), duplicate_file.read_bytes())
        self.assertEqual(child_file.read_bytes(), duplicate_child_file.read_bytes())
        self.assertEqual("alpha copy 2", self.window.get_node_path(self.window.selected_node))
        rename.assert_called_once_with()

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

    def test_move_node_uses_next_clicked_node_as_parent(self):
        self.write_node("alpha", "Alpha text")
        self.write_node("beta", "Beta text")
        self.window.populateNodeTree()
        alpha = self.window.find_self("alpha")
        beta = self.window.find_self("beta")
        self.window.selected_node = alpha
        self.window.beginMoveNode()

        event = SimpleNamespace(x=10, y=20)
        with mock.patch.object(self.window.tree, "identify", return_value=beta):
            result = self.window.completeMoveNode(event)

        self.assertEqual("break", result)
        self.assertIsNone(self.window.move_source_node)
        self.assertFalse((self.node_dir / "alpha").exists())
        self.assertTrue((self.node_dir / "beta" / "alpha").is_dir())
        self.assertTrue((self.node_dir / "beta" / "alpha.rtf").is_file())
        self.assertEqual(os.path.join("beta", "alpha"), self.window.get_node_path(self.window.selected_node))

    def test_escape_or_right_click_cancels_pending_move(self):
        self.write_node("alpha", "Alpha text")
        self.window.populateNodeTree()
        self.window.selected_node = self.window.find_self("alpha")

        self.window.beginMoveNode()
        self.assertEqual("break", self.window.cancelNodeInteraction())
        self.assertIsNone(self.window.move_source_node)

        self.window.beginMoveNode()
        event = SimpleNamespace(x=10, y=20, x_root=110, y_root=220)
        self.assertEqual("break", self.window.showNodeContextMenu(event))
        self.assertIsNone(self.window.move_source_node)

    def test_inline_rename_changes_only_the_node_name(self):
        self.write_node("parent", "Parent text")
        self.write_node(Path("parent") / "child", "Child text")
        self.window.populateNodeTree()
        parent = self.window.find_self("parent")
        self.window.populateNodeTree(str(self.node_dir / "parent") + os.sep, parent)
        child = self.window.find_self(os.path.join("parent", "child"))
        entry = mock.Mock()
        entry.get.return_value = "renamed"
        self.window.rename_entry = entry

        self.window.finishInlineRename(child, os.path.join("parent", "child"))

        entry.destroy.assert_called_once_with()
        self.assertTrue((self.node_dir / "parent" / "renamed").is_dir())
        self.assertTrue((self.node_dir / "parent" / "renamed.rtf").is_file())
        self.assertFalse((self.node_dir / "renamed").exists())

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

    def test_insert_table_creates_pipe_styled_rows_with_elastic_tab_tag(self):
        self.window.insertTable(2, 3)

        self.assertEqual(
            "| Cell 1\t| Cell 2\t| Cell 3\t|\n"
            "| Cell 4\t| Cell 5\t| Cell 6\t|\n",
            self.window.text.get("1.0", "end"),
        )
        table_tag = next(
            tag for tag in self.window.text.tag_names("1.0")
            if tag.startswith(self.window.TABLE_TAG_PREFIX)
        )
        self.assertTrue(self.window.text.tag_cget(table_tag, "tabs"))
        self.assertIn(table_tag, self.window.text.tag_names("2.0"))

    def test_insert_table_with_header_adds_separator_row(self):
        self.window.insertTable(3, 2, has_header=True)

        self.assertEqual(
            "| Col A\t| Col B\t|\n"
            "| ------\t| ------\t|\n"
            "| Cell 1\t| Cell 2\t|\n"
            "| Cell 3\t| Cell 4\t|\n",
            self.window.text.get("1.0", "end"),
        )

    def test_header_separator_grows_to_match_widest_column_text(self):
        self.window.insertTable(3, 3, has_header=True)
        self.window.text.insert("1.7", " Aaaaaaa")
        self.window.text.insert("3.8", " Text")

        self.window.refreshTableLayout()

        self.assertEqual(
            "| Col A Aaaaaaa\t| Col B\t| Col C\t|\n"
            "| -------------\t| ------\t| ------\t|\n"
            "| Cell 1 Text\t| Cell 2\t| Cell 3\t|\n"
            "| Cell 4\t| Cell 5\t| Cell 6\t|\n",
            self.window.text.get("1.0", "end"),
        )

    def test_table_layout_uses_one_contiguous_tag_range_per_table(self):
        table = self.window.buildTableText(5, 4)
        self.window.text.insert("1.0", f"{table}\n\n{table}")

        self.window.refreshTableLayout()

        table_tags = [
            tag
            for tag in self.window.text.tag_names()
            if tag.startswith(self.window.TABLE_TAG_PREFIX)
        ]
        table_ranges = [
            (str(start), str(finish))
            for tag in table_tags
            for start, finish in zip(
                self.window.text.tag_ranges(tag)[0::2],
                self.window.text.tag_ranges(tag)[1::2],
            )
        ]
        self.assertEqual(
            [("1.0", "5.41"), ("7.0", "11.41")],
            table_ranges,
        )
        self.assertEqual(1, len(table_tags))

    def test_table_width_measurement_preserves_mixed_font_styles(self):
        self.window.text.insert("1.0", "| Wide\t| Narrow\t|")
        bold_style = self.window.defaultTextStyle()
        bold_style["bold"] = True
        bold_tag = self.window.getStyleTag(bold_style)
        self.window.text.tag_add(bold_tag, "1.2", "1.6")

        widths = self.window.tableLineCellWidths(1)

        regular_font = self.window.textStyleFont(self.window.defaultTextStyle())
        self.assertEqual(
            [
                regular_font.measure("| ")
                + self.window.textStyleFont(bold_style).measure("Wide"),
                regular_font.measure("| Narrow"),
                regular_font.measure("|"),
            ],
            widths,
        )

    def test_rtf_export_and_import_round_trips_tabs(self):
        self.window.openFile = str(self.node_dir / "scratch.rtf")
        self.window.text.insert("1.0", "Name\tValue")

        rtf = self.window.convertToRTF("1.0", "end")

        self.assertIn(r"Name{\tab }Value", rtf)

        parsed = app.RTFParser(rtf).parseme()
        self.window.text.delete("1.0", "end")
        self.window.displayNestedRTFStructure(parsed)

        self.assertEqual("Name\tValue\n", self.window.text.get("1.0", "end"))

    def test_plain_text_copy_sets_normal_text_clipboard_formats(self):
        self.window.text.insert("1.0", "Plain text")
        self.window.text.tag_add("sel", "1.0", "1.10")

        self.window.copyFromClipboard(None)

        self.assertIn(
            ("Plain text".encode("utf-16-le"), self.window.clip.UNITEXT),
            self.window.clip.set_calls,
        )
        self.assertIn(
            ("Plain text".encode("ansi"), self.window.clip.TEXT),
            self.window.clip.set_calls,
        )
        self.assertTrue(any(
            data_type == self.window.clip.RTF_NO_OBJ
            for _, data_type in self.window.clip.set_calls
        ))

    def test_rich_text_paste_inserts_at_text_cursor(self):
        self.window.text.insert("1.0", "Hello world")
        self.window.text.mark_set("insert", "1.6")
        self.window.clip.get_clipboard = lambda: r"{\rtf1\ansi pasted }"

        result = self.window.pasteFromClipboard(None)

        self.assertEqual("break", result)
        self.assertEqual("Hello pasted world\n", self.window.text.get("1.0", "end"))

    def test_rich_text_paste_replaces_selected_text(self):
        self.window.text.insert("1.0", "Hello old text")
        self.window.text.tag_add("sel", "1.6", "1.14")
        self.window.text.mark_set("insert", "1.0")
        self.window.clip.get_clipboard = lambda: r"{\rtf1\ansi new text}"

        result = self.window.pasteFromClipboard(None)

        self.assertEqual("break", result)
        self.assertEqual("Hello new text\n", self.window.text.get("1.0", "end"))
        self.assertFalse(self.window.text.tag_ranges("sel"))

    def test_copy_table_expands_tabs_to_spaces_for_plain_text_clipboard(self):
        self.window.insertTable(3, 2, has_header=True)
        self.window.text.tag_add("sel", "1.0", "end-1c")

        self.window.copyFromClipboard(None)

        unicode_payload = next(
            data
            for data, data_type in self.window.clip.set_calls
            if data_type == self.window.clip.UNITEXT
        )
        self.assertEqual(
            "| Col A  | Col B  |\n"
            "| ------ | ------ |\n"
            "| Cell 1 | Cell 2 |\n"
            "| Cell 3 | Cell 4 |",
            unicode_payload.decode("utf-16-le"),
        )
        self.assertNotIn(b"\t", unicode_payload)

    def test_formatted_text_copy_sets_plain_text_and_rtf_formats(self):
        self.window.openFile = str(self.node_dir / "scratch.rtf")
        self.window.text.insert("1.0", "Bold")
        self.window.text.tag_add("sel", "1.0", "1.4")
        self.window.toggleBoldForSelection()
        self.window.text.tag_add("sel", "1.0", "1.4")

        self.window.copyFromClipboard(None)

        copied_types = [
            data_type
            for _, data_type in self.window.clip.set_calls
        ]
        self.assertIn(self.window.clip.UNITEXT, copied_types)
        self.assertIn(self.window.clip.TEXT, copied_types)
        self.assertIn(self.window.clip.RTF_NO_OBJ, copied_types)

    def test_copy_color_when_selection_matches_exact_tag_boundaries(self):
        self.window.openFile = str(self.node_dir / "scratch.rtf")
        self.window.text.insert("1.0", "Red plain")
        self.window.text.tag_add("sel", "1.0", "1.3")
        self.window.applyStylePropertyToSelection("color", "#ff0000")
        self.window.text.tag_add("sel", "1.0", "1.3")

        self.window.copyFromClipboard(None)

        rtf_payload = next(
            data
            for data, data_type in self.window.clip.set_calls
            if data_type == self.window.clip.RTF_NO_OBJ
        ).decode("utf-8")
        self.assertIn(r"{\colortbl ;\red255\green0\blue0;}", rtf_payload)
        self.assertIn(r"{\cf1 Red}", rtf_payload)

    def test_copy_color_when_selection_starts_inside_formatted_word(self):
        self.window.openFile = str(self.node_dir / "scratch.rtf")
        self.window.text.insert("1.0", "Colored")
        self.window.text.tag_add("sel", "1.0", "1.7")
        self.window.applyStylePropertyToSelection("color", "#ff0000")
        self.window.text.tag_remove("sel", "1.0", "end")
        self.window.text.tag_add("sel", "1.2", "1.5")

        self.window.copyFromClipboard(None)

        rtf_payload = next(
            data
            for data, data_type in self.window.clip.set_calls
            if data_type == self.window.clip.RTF_NO_OBJ
        ).decode("utf-8")
        self.assertIn(r"{\colortbl ;\red255\green0\blue0;}", rtf_payload)
        self.assertIn(r"{\cf1 lor}", rtf_payload)
        self.assertLess(rtf_payload.index(r"{\fonttbl"), rtf_payload.index(r"\pard"))
        self.assertLess(rtf_payload.index(r"{\colortbl"), rtf_payload.index(r"\pard"))

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

    def test_hyperlink_round_trips_target_and_visible_text(self):
        self.window.text.insert("1.0", "Read the docs")

        tag = self.window.applyHyperlinkToRange(
            "1.5",
            "1.13",
            "url",
            "https://example.com/docs?topic=rtf#links",
        )
        exported = self.window.convertToRTF("1.0", "end")

        self.assertIn(r"\supertextlink", exported)
        self.assertNotIn("https://example.com/docs", exported)
        self.assertEqual(
            "https://example.com/docs?topic=rtf#links",
            self.window.hyperlink_tags[tag]["target"],
        )

        self.window.text.delete("1.0", "end")
        self.window.hyperlink_tags = {}
        self.window.hyperlink_tag_counter = 0
        self.window.displayNestedRTFStructure(app.RTFParser(exported).parseme())

        restored_tag = self.window.hyperlinkTagAt("1.6")
        self.assertIsNotNone(restored_tag)
        self.assertEqual(
            {
                "kind": "url",
                "target": "https://example.com/docs?topic=rtf#links",
            },
            self.window.hyperlink_tags[restored_tag],
        )
        self.assertEqual(
            "Read the docs",
            self.window.text.get("1.0", "end-1c"),
        )

    def test_hyperlink_rich_text_paste_tags_the_inserted_range(self):
        self.window.text.insert("1.0", "Link")
        self.window.applyHyperlinkToRange(
            "1.0",
            "1.4",
            "url",
            "mailto:test@example.com",
        )
        copied_rtf = self.window.convertToRTF("1.0", "1.4")

        self.window.text.delete("1.0", "end")
        self.window.hyperlink_tags = {}
        self.window.hyperlink_tag_counter = 0
        self.window.text.insert("1.0", "Before  after")
        paste_mark = "__test_hyperlink_paste"
        self.window.text.mark_set(paste_mark, "1.7")
        self.window.text.mark_gravity(paste_mark, "right")
        try:
            self.window.displayNestedRTFStructure(
                app.RTFParser(copied_rtf).parseme(),
                paste_mark,
            )
        finally:
            self.window.text.mark_unset(paste_mark)

        self.assertEqual(
            "Before Link after",
            self.window.text.get("1.0", "end-1c"),
        )
        restored_tag = self.window.hyperlinkTagAt("1.8")
        self.assertEqual(
            "mailto:test@example.com",
            self.window.hyperlink_tags[restored_tag]["target"],
        )

    def test_relinking_part_of_a_link_preserves_adjacent_targets(self):
        self.window.text.insert("1.0", "abcdef")
        self.window.applyHyperlinkToRange(
            "1.0",
            "1.6",
            "url",
            "https://old.example",
        )
        self.window.applyHyperlinkToRange(
            "1.2",
            "1.4",
            "url",
            "https://new.example",
        )

        exported = self.window.convertToRTF("1.0", "end")
        self.window.text.delete("1.0", "end")
        self.window.hyperlink_tags = {}
        self.window.hyperlink_tag_counter = 0
        self.window.displayNestedRTFStructure(app.RTFParser(exported).parseme())

        targets = [
            self.window.hyperlink_tags[
                self.window.hyperlinkTagAt(index)
            ]["target"]
            for index in ("1.1", "1.3", "1.5")
        ]
        self.assertEqual(
            [
                "https://old.example",
                "https://new.example",
                "https://old.example",
            ],
            targets,
        )

    def test_notebook_hyperlink_opens_linked_node(self):
        with mock.patch.object(
            self.window,
            "selectNodePath",
            return_value="ITEM_2",
        ) as select_node:
            result = self.window.activateHyperlink("node", "parent/child")

        self.assertEqual("break", result)
        select_node.assert_called_once_with(os.path.join("parent", "child"))

    def test_file_hyperlink_uses_the_operating_system_url_handler(self):
        target = "file:///C:/notes/reference.pdf"
        with mock.patch.object(app.os, "startfile", create=True) as startfile:
            result = self.window.activateHyperlink("file", target)

        self.assertEqual("break", result)
        startfile.assert_called_once_with(target)

    def test_formatting_at_document_start_does_not_spill_after_round_trip(self):
        self.window.text.insert("1.0", "Bold plain text")
        self.window.applyStylePropertyToRange("1.0", "1.4", "bold", True)

        rtf = self.window.convertToRTF("1.0", "end")

        self.window.text.delete("1.0", "end")
        self.window.style_tags = {}
        self.window.style_tag_names = {}
        self.window.style_tag_counter = 0
        self.window.displayNestedRTFStructure(app.RTFParser(rtf).parseme())

        self.assertTrue(self.window.getTextStyleAt("1.0")["bold"])
        self.assertFalse(self.window.getTextStyleAt("1.5")["bold"])

    def test_centered_text_is_tagged_and_exported_to_rtf(self):
        self.window.openFile = str(self.node_dir / "scratch.rtf")
        self.window.text.insert("1.0", "Title")
        self.window.text.tag_add("sel", "1.0", "1.5")

        self.window.toggleCenterAlignmentForSelection()

        style = self.window.getTextStyleAt("1.0")
        self.assertEqual("center", style["alignment"])
        self.assertTrue(self.window.center_menu_var.get())
        style_tag = next(
            tag for tag in self.window.text.tag_names("1.0")
            if tag.startswith(self.window.FORMAT_TAG_PREFIX)
        )
        self.assertEqual("", self.window.text.tag_cget(style_tag, "justify"))

        self.window.text.winfo_width = lambda: 500
        self.window.refreshCenteredTextLayout()
        alignment_tag = next(
            tag for tag in self.window.text.tag_names("1.0")
            if tag.startswith(self.window.ALIGNMENT_TAG_PREFIX)
        )
        padding_start, padding_end = self.window.text.tag_ranges(alignment_tag)
        padding = self.window.text.get(padding_start, padding_end)
        self.assertGreater(len(padding), 0)
        self.assertEqual({" "}, set(padding))
        self.assertEqual("Title", self.window.text.get(padding_end, "1.end"))

        rtf = self.window.convertToRTF("1.0", "end")

        self.assertIn(r"{\qc Title}", rtf)
        self.assertNotIn(padding + "Title", rtf)

    def test_alignment_padding_is_not_copied_as_plain_text(self):
        self.window.text.insert("1.0", "Title")
        self.window.text.tag_add("sel", "1.0", "1.5")
        self.window.toggleCenterAlignmentForSelection()
        self.window.text.winfo_width = lambda: 500
        self.window.refreshCenteredTextLayout()

        dumped_text = self.window.text.dump("1.0", "1.end")

        self.assertEqual(["Title"], self.window.dumpTextWithoutAlignmentPadding(dumped_text))

    def test_centered_layout_refresh_keeps_unchanged_padding_in_place(self):
        self.window.text.insert("1.0", "Title\nBody")
        self.window.text.tag_add("sel", "1.0", "1.5")
        self.window.toggleCenterAlignmentForSelection()
        self.window.text.winfo_width = lambda: 500
        self.window.refreshCenteredTextLayout()
        before = self.window.text.dump("1.0", "end")

        with mock.patch.object(
            self.window.text,
            "delete",
            wraps=self.window.text.delete,
        ) as delete_mock:
            self.window.refreshCenteredTextLayout()

        self.assertFalse(delete_mock.called)
        self.assertEqual(before, self.window.text.dump("1.0", "end"))

    def test_centered_text_can_be_toggled_back_to_left_after_layout_refresh(self):
        self.window.text.insert("1.0", "Title")
        self.window.text.tag_add("sel", "1.0", "1.5")
        self.window.toggleCenterAlignmentForSelection()
        self.window.text.winfo_width = lambda: 500
        self.window.refreshCenteredTextLayout()

        self.window.text.tag_remove("sel", "1.0", "end")
        alignment_tag = next(
            tag for tag in self.window.text.tag_names("1.0")
            if tag.startswith(self.window.ALIGNMENT_TAG_PREFIX)
        )
        _, title_start = self.window.text.tag_ranges(alignment_tag)
        self.window.text.tag_add("sel", title_start, f"{title_start}+5c")
        self.window.toggleCenterAlignmentForSelection()

        self.assertEqual("left", self.window.getTextStyleAt("1.0")["alignment"])
        self.window.refreshCenteredTextLayout()
        self.assertEqual("Title", self.window.text.get("1.0", "1.end"))

    def test_cursor_at_start_of_centered_text_reports_centered_and_can_uncenter(self):
        self.window.text.insert("1.0", "Title")
        self.window.text.tag_add("sel", "1.0", "1.5")
        self.window.toggleCenterAlignmentForSelection()
        self.window.text.winfo_width = lambda: 500
        self.window.refreshCenteredTextLayout()

        self.window.text.tag_remove("sel", "1.0", "end")
        alignment_tag = next(
            tag for tag in self.window.text.tag_names("1.0")
            if tag.startswith(self.window.ALIGNMENT_TAG_PREFIX)
        )
        _, title_start = self.window.text.tag_ranges(alignment_tag)
        self.window.text.mark_set("insert", title_start)

        self.window.updateToolbarStyleFromSelection()
        self.assertTrue(self.window.center_menu_var.get())

        self.window.toggleCenterAlignmentForSelection()

        self.assertFalse(self.window.center_menu_var.get())
        self.window.refreshCenteredTextLayout()
        self.assertEqual("Title", self.window.text.get("1.0", "1.end"))
        self.assertEqual("left", self.window.getTextStyleAt("1.0")["alignment"])

    def test_cursor_on_blank_line_after_centered_text_does_not_uncenter_previous_line(self):
        self.window.text.insert("1.0", "Title\n")
        self.window.text.tag_add("sel", "1.0", "1.5")
        self.window.toggleCenterAlignmentForSelection()
        self.window.text.winfo_width = lambda: 500
        self.window.refreshCenteredTextLayout()

        self.window.text.tag_remove("sel", "1.0", "end")
        self.window.text.mark_set("insert", "2.0")

        self.window.updateToolbarStyleFromSelection()
        self.assertFalse(self.window.center_menu_var.get())

        self.window.toggleCenterAlignmentForSelection()

        self.assertEqual("center", self.window.getTextStyleAt("1.0")["alignment"])
        self.window.refreshCenteredTextLayout()
        self.assertEqual("Title", self.window.text.get("1.0", "1.end").strip())

    def test_cursor_on_text_line_after_centered_text_reports_left_and_preserves_previous_line(self):
        self.window.text.insert("1.0", "Title\nBody")
        self.window.text.tag_add("sel", "1.0", "1.5")
        self.window.toggleCenterAlignmentForSelection()
        self.window.text.winfo_width = lambda: 500
        self.window.refreshCenteredTextLayout()

        self.window.text.tag_remove("sel", "1.0", "end")
        self.window.text.mark_set("insert", "2.0")

        self.window.updateToolbarStyleFromSelection()
        self.assertFalse(self.window.center_menu_var.get())

        self.window.toggleCenterAlignmentForSelection()

        self.assertEqual("center", self.window.getTextStyleAt("1.0")["alignment"])
        self.assertEqual("center", self.window.getTextStyleAt("2.0")["alignment"])
        self.window.refreshCenteredTextLayout()
        self.assertEqual("Title", self.window.text.get("1.0", "1.end").strip())
        self.assertEqual("Body", self.window.text.get("2.0", "2.end").strip())

    def test_unchecking_center_menu_on_next_line_does_not_toggle_adjacent_lines(self):
        self.window.text.insert("1.0", "Title\nBody")
        self.window.text.tag_add("sel", "1.0", "1.5")
        self.window.toggleCenterAlignmentForSelection()
        self.window.text.winfo_width = lambda: 500
        self.window.refreshCenteredTextLayout()

        self.window.text.tag_remove("sel", "1.0", "end")
        self.window.text.mark_set("insert", "2.0")
        self.window.center_menu_var.set(False)

        self.window.applyCenterAlignmentFromMenu()

        self.assertEqual("center", self.window.getTextStyleAt("1.0")["alignment"])
        self.assertEqual("left", self.window.getTextStyleAt("2.0")["alignment"])
        self.window.refreshCenteredTextLayout()
        self.assertEqual("Title", self.window.text.get("1.0", "1.end").strip())
        self.assertEqual("Body", self.window.text.get("2.0", "2.end").strip())

    def test_display_nested_rtf_structure_imports_centered_text(self):
        rtf_text = (
            r"{\rtf1\ansi\pard "
            r"{\fonttbl{\f0\fswiss Consolas;}}\f0 "
            r"\qc Centered\par \ql Left}"
        )

        parsed = app.RTFParser(rtf_text).parseme()

        self.window.displayNestedRTFStructure(parsed)

        self.assertEqual("Centered\nLeft\n", self.window.text.get("1.0", "end"))
        self.assertEqual("center", self.window.getTextStyleAt("1.0")["alignment"])
        self.assertEqual("left", self.window.getTextStyleAt("2.0")["alignment"])

    def test_resized_embedded_image_exports_resized_dimensions(self):
        self.window.openFile = str(self.node_dir / "scratch.rtf")
        embedded_name = self.window.createEmbeddedImage(
            "1.0",
            app.Image.new("RGB", (40, 20), "red"),
        )

        self.window.resizeEmbeddedImage(embedded_name, 80, 40)
        rtf = self.window.convertToRTF("1.0", "end")

        self.assertIn(r"\picw1200\pich600", rtf)

    def test_shift_image_resize_preserves_aspect_ratio(self):
        resize_state = {
            "handle": "se",
            "start_x": 10,
            "start_y": 10,
            "start_width": 40,
            "start_height": 20,
        }

        width, height = self.window.calculateImageResizeSize(
            resize_state,
            70,
            20,
            preserve_aspect=True,
        )

        self.assertEqual((100, 50), (width, height))

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

    def test_font_menu_without_selection_sets_style_for_typed_text(self):
        self.window.text.insert("1.0", "Old ")
        self.window.text.mark_set("insert", "end-1c")

        self.window.font_family_var.set("Arial")
        self.window.applySelectedFontFamily()
        self.window.font_size_var.set(20)
        self.window.applySelectedFontSize()
        self.window.insertTypedText("New")

        self.assertEqual("Old New\n", self.window.text.get("1.0", "end"))
        old_style = self.window.getTextStyleAt("1.0")
        new_style = self.window.getTextStyleAt("1.4")
        self.assertEqual(self.window.DEFAULT_FONT_FAMILY, old_style["font_family"])
        self.assertEqual(self.window.DEFAULT_FONT_SIZE, old_style["font_size"])
        self.assertEqual("Arial", new_style["font_family"])
        self.assertEqual(20, new_style["font_size"])

    def test_bold_without_selection_sets_style_for_typed_text(self):
        self.window.toggleBoldForSelection()
        self.window.insertTypedText("Bold")

        style = self.window.getTextStyleAt("1.0")
        self.assertTrue(style["bold"])
        self.assertTrue(self.window.bold_menu_var.get())

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

    def test_embedded_file_round_trips_through_rtf(self):
        name = self.window.createEmbeddedFile('1.0', 'payload.bin', b'\x00\xffdata')

        rtf = self.window.convertToRTF('1.0', 'end')
        self.assertIn(r'\supertextfile', rtf)
        self.window.text.delete('1.0', 'end')
        self.window.embedded_files = {}
        self.window.displayNestedRTFStructure(app.RTFParser(rtf).parseme())

        self.assertEqual(1, len(self.window.embedded_files))
        attachment = next(iter(self.window.embedded_files.values()))
        self.assertEqual('payload.bin', attachment['filename'])
        self.assertEqual(b'\x00\xffdata', attachment['data'])

    def test_text_around_embedded_file_round_trips_through_rtf(self):
        self.window.text.insert('1.0', 'Before ')
        self.window.createEmbeddedFile('end-1c', 'payload.bin', b'payload')
        self.window.text.insert('end-1c', ' after')

        rtf = self.window.convertToRTF('1.0', 'end')
        self.window.text.delete('1.0', 'end')
        self.window.embedded_files = {}
        self.window.displayNestedRTFStructure(app.RTFParser(rtf).parseme())

        self.assertEqual('Before  after\n', self.window.text.get('1.0', 'end'))
        self.assertEqual(1, len(self.window.embedded_files))
        attachment = next(iter(self.window.embedded_files.values()))
        self.assertEqual('payload.bin', attachment['filename'])
        self.assertEqual(b'payload', attachment['data'])

    def test_paste_binary_file_embeds_a_snapshot(self):
        source = self.root / 'payload.bin'
        source.write_bytes(b'original bytes')
        self.window.clip.get_file_paths = lambda: [str(source)]

        self.assertEqual('break', self.window.pasteFromClipboard())
        source.write_bytes(b'changed')

        attachment = next(iter(self.window.embedded_files.values()))
        self.assertEqual('payload.bin', attachment['filename'])
        self.assertEqual(b'original bytes', attachment['data'])

    def test_copy_attachment_sets_file_drop_and_preferred_copy_effect(self):
        name = self.window.createEmbeddedFile('1.0', 'payload.bin', b'payload')

        self.assertEqual('break', self.window.copyEmbeddedFile(name))

        self.assertEqual(
            ['Preferred DropEffect', 'FileNameW'],
            self.window.clip.registered_formats,
        )
        self.assertEqual(self.window.clip.FILES, self.window.clip.set_calls[0][1])
        self.assertEqual((struct.pack('<I', 1), 0xC123), self.window.clip.set_calls[1])
        filename_payload, filename_format = self.window.clip.set_calls[2]
        self.assertEqual(0xC124, filename_format)
        self.assertTrue(filename_payload.endswith('payload.bin'.encode('utf-16-le') + b'\0'))

    def test_calculate_attachment_sha1_displays_and_returns_digest(self):
        data = b'payload'
        name = self.window.createEmbeddedFile('1.0', 'payload.bin', data)
        expected_digest = hashlib.sha1(data).hexdigest()

        with mock.patch.object(self.window, 'showSha1HashDialog') as show_dialog:
            digest = self.window.calculateEmbeddedFileSha1(name)

        self.assertEqual(expected_digest, digest)
        show_dialog.assert_called_once_with('payload.bin', expected_digest)

    def test_calculate_attachment_sha1_ignores_missing_attachment(self):
        with mock.patch.object(self.window, 'showSha1HashDialog') as show_dialog:
            digest = self.window.calculateEmbeddedFileSha1('missing')

        self.assertIsNone(digest)
        show_dialog.assert_not_called()

    def test_sha1_dialog_makes_digest_selectable_and_copyable(self):
        digest = hashlib.sha1(b'payload').hexdigest()

        with mock.patch.object(self.window, 'copySha1Hash') as copy_hash:
            dialog = self.window.showSha1HashDialog('payload.bin', digest)
            try:
                content = dialog.winfo_children()[0]
                digest_entry = next(
                    child
                    for child in content.winfo_children()
                    if isinstance(child, app.ttk.Entry)
                )
                copy_button = next(
                    child
                    for child in content.winfo_children()
                    if isinstance(child, app.ttk.Button) and child.cget('text') == 'Copy'
                )
                copy_button.invoke()

                self.assertEqual(digest, digest_entry.get())
                self.assertIn('readonly', digest_entry.state())
                self.assertEqual((0, len(digest)), (
                    digest_entry.index('sel.first'),
                    digest_entry.index('sel.last'),
                ))
                copy_hash.assert_called_once_with(digest)
                self.assertEqual('Copied!', copy_button.cget('text'))
            finally:
                dialog.destroy()

    def test_copy_sha1_hash_places_plain_text_on_clipboard(self):
        digest = hashlib.sha1(b'payload').hexdigest()

        with (
            mock.patch.object(self.window.window, 'clipboard_clear') as clear,
            mock.patch.object(self.window.window, 'clipboard_append') as append,
        ):
            result = self.window.copySha1Hash(digest)

        self.assertEqual('break', result)
        clear.assert_called_once_with()
        append.assert_called_once_with(digest)

    def test_attachment_context_menu_includes_sha1_action(self):
        name = self.window.createEmbeddedFile('1.0', 'payload.bin', b'payload')
        event = SimpleNamespace(x_root=110, y_root=220)
        menu = mock.Mock()

        with (
            mock.patch.object(app.tk, 'Menu', return_value=menu),
            mock.patch.object(self.window, 'calculateEmbeddedFileSha1') as calculate,
        ):
            result = self.window.showEmbeddedFileMenu(event, name)
            sha1_command = next(
                call.kwargs['command']
                for call in menu.add_command.call_args_list
                if call.kwargs.get('label') == 'Calculate SHA-1 hash'
            )
            sha1_command()

        self.assertEqual('break', result)
        menu.add_separator.assert_called_once_with()
        calculate.assert_called_once_with(name)
        menu.tk_popup.assert_called_once_with(110, 220)

    def test_text_motion_restores_text_cursor_without_reconfiguring_repeatedly(self):
        self.window.current_text_cursor = "sb_h_double_arrow"
        event = SimpleNamespace(x=5, y=5)

        with mock.patch.object(self.window.text, "configure", wraps=self.window.text.configure) as configure_mock:
            self.window.updateImageResizeCursor(event)
            self.window.updateImageResizeCursor(event)

        configure_mock.assert_called_once_with(cursor=self.window.TEXT_CURSOR)
        self.assertEqual(self.window.TEXT_CURSOR, self.window.current_text_cursor)


if __name__ == "__main__":
    unittest.main()
