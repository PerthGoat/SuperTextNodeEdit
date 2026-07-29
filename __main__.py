# GUI utilities
# Tkinter
# Chosen because Tkinter is shipped standard with Python and does not require GTK
# or anything complex to get it running
import tkinter as tk
from tkinter import colorchooser, messagebox, font, simpledialog, ttk

# threading
# used for action queue
from dataclasses import dataclass, field
import queue
import datetime

# IO utilities
# these handle parsing, renaming, removing, and moving the various node/file trees
import io
import os
import glob
import hashlib
import shutil
import struct
import tempfile
import threading

import configparser
import re
from typing import Any, cast, TypeGuard

# PIL functions used for grabbing the clipboard in a cross-platform way
from PIL import Image, ImageTk, ImageGrab

# user defined functions
# scrollable textboxes
from src.uicomponents import ScrollableText, ScrollableTreeView
# RTF parsing
from src.RTFParser import RTFParseError, RTFParser
from src.search_index import NoteSearchIndex
from src.archive_store import (
    ArchiveConflictError,
    ArchiveError,
    NoteArchiveStore,
)

# for image copying
from src.os_specific import Clipboard

# for helper functions
from src.helperfunctions import *

BASE_CONFIG_CONST : str = r'''; config file for rtf tree program
[constants]
RTF_HEADER={\rtf1\ansi\pard {\fonttbl\f0\fswiss Consolas;}\f0 
nodeDir=nodes/
'''

@dataclass(order=True)
class PrioritizedItem:
    priority: int
    item: Any=field(compare=False)
    descr: str=field(compare=False)

@dataclass
class OpenDocument:
    """Editor and document-specific state for one open tab."""
    tab_id: str
    text: Any
    path: str = ''
    relative_path: str = ''
    tkinter_imagelist: list = field(default_factory=list)
    embedded_images: dict = field(default_factory=dict)
    embedded_files: dict = field(default_factory=dict)
    font_table: dict = field(default_factory=lambda: {0: "Consolas"})
    color_table: dict = field(default_factory=lambda: {0: None})
    style_tags: dict = field(default_factory=dict)
    style_tag_names: dict = field(default_factory=dict)
    style_tag_counter: int = 0
    typing_style: dict = field(default_factory=lambda: {
        "font_family": "Consolas",
        "font_size": 12,
        "color": None,
        "bold": False,
        "italic": False,
        "alignment": "left",
    })
    current_text_cursor: str = 'xterm'
    image_resize_state: Any = None
    dirty: bool = False
    loading: bool = False

# this is the meat of the program, that joins together the uicomponents, RTF parser, and INI config into one functional UI and software
class RTFWindow:
    ACTION_QUEUE_POLL_MS = 10
    TREE_SINGLE_CLICK_DELAY_MS = 400
    FORMAT_TAG_PREFIX = "rtf_style_"
    ALIGNMENT_TAG_PREFIX = "rtf_alignment_"
    TABLE_TAG_PREFIX = "rtf_table_"
    DEFAULT_FONT_FAMILY = "Consolas"
    DEFAULT_FONT_SIZE = 12
    DEFAULT_TEXT_COLOR = None
    TEXT_CURSOR = 'xterm'
    IMAGE_RESIZE_HANDLE_SIZE = 8
    IMAGE_RESIZE_MIN_SIZE = 8
    TABLE_MIN_CELL_WIDTH = 48
    TABLE_COLUMN_GAP = 24

    def __init__(self, configFile='rtfjournal.ini', start_mainloop=True, start_worker=True):
        self.start_mainloop = start_mainloop
        self.start_worker = start_worker
        
        # make sure a config file exists, and if not, create a base one
        if not os.path.exists(configFile):
            with open(configFile, 'w') as fi:
                fi.write(BASE_CONFIG_CONST)

        if not os.path.isfile(configFile):
            messagebox.showerror('FAILOUT', 'FAILOUT: CONFIGFILE IS NOT A FILE!')

        config_dict = configparser.ConfigParser()
        config_dict.read(configFile)
        
        # set up public variables to this class
        self.RTF_HEADER = config_dict['constants']['RTF_HEADER'] + ' ' # read in RTF header
        self.nodeDir = os.path.normpath(config_dict['constants']['nodeDir']) + os.sep # read in directory to hold RTF file tree
        self.search_index = NoteSearchIndex(self.nodeDir)
        self.archive_store = NoteArchiveStore(self.nodeDir)
        self.openFile = '' # holds the currently open file for easy saving etc.
        self.tkinter_imagelist = [] # tkinter has a garbage collector bug where images need to be kept in a list to prevent them being garbage collected
        self.embedded_images = {}
        self.embedded_files = {}
        self.attachment_tempdir = tempfile.TemporaryDirectory(prefix='supertext-attachments-')
        self.image_resize_state = None
        self.current_text_cursor = self.TEXT_CURSOR

        # 1 pixel = 15 twips
        self.rtf_img_factor = 15

        self.font_table = {0: self.DEFAULT_FONT_FAMILY}
        self.color_table = {0: self.DEFAULT_TEXT_COLOR}
        self.style_tags = {}
        self.style_tag_names = {}
        self.style_tag_counter = 0
        self.typing_style = self.defaultTextStyle()
        self.toolbar_style_after_id = None
        self.center_layout_after_id = None
        self.table_layout_after_id = None

        # track if a UI popup is open or not to prevent spawning multiple windows
        self.UI_popup = None
        self.search_popup = None
        self.search_generation = 0
        self.search_results = {}
        self.archive_popup = None
        self.archive_generation = 0
        self.archive_results = {}
        self.rename_entry = None
        self.move_source_node = None
        self.tree_single_click_after_id = None
        self.ignore_next_tree_release = False
        self.open_documents_by_tab = {}
        self.open_documents_by_path = {}
        self.active_document = None
        
        # set up OS specific clipboard for copying images
        self.clip = Clipboard()
        
        # a queue to balance different types of actions
        # has priorities, which is nice
        # 0 = highest priority
        self.actionQueue = queue.PriorityQueue()
        self._queue_after_id = None

        # create main user interface window
        self.createTkinterWindow()
    
    # main user interface
    def createTkinterWindow(self):
        self.window = tk.Tk()
        self.window.title('SuperText \u2014 Node-Based Text Editor')
        self.window.geometry('1200x650') # starting window size, I thought this size was pretty good
        self.window.grid_columnconfigure(1, weight=1) # for responsive-resize
        self.window.grid_rowconfigure(0, weight=1) # for responsive-resize
        original_destroy = self.window.destroy
        def destroyWindow():
            self.cancelPendingNodePreview()
            self.cancelScheduledToolbarStyleUpdate()
            self.cancelScheduledCenteredTextLayoutRefresh()
            self.cancelScheduledTableLayoutRefresh()
            self.attachment_tempdir.cleanup()
            original_destroy()
        self.window.destroy = destroyWindow
        self.window.bind('<Destroy>', self.cancelScheduledCenteredTextLayoutRefresh, add='+')
        self.window.protocol('WM_DELETE_WINDOW', self.closeWindow)
        
        self.tkinter_font = tk.font.Font(family='Consolas', size=12)

        available_fonts = sorted(set(font.families()))
        preferred_fonts = [
            "Consolas",
            "Arial",
            "Calibri",
            "Times New Roman",
            "Courier New",
            "Verdana",
        ]
        font_values = preferred_fonts + [
            family for family in available_fonts if family not in preferred_fonts
        ]

        self.font_values = font_values
        self.font_family_var = tk.StringVar(value=self.DEFAULT_FONT_FAMILY)
        self.font_size_var = tk.IntVar(value=self.DEFAULT_FONT_SIZE)
        self.bold_menu_var = tk.BooleanVar(value=False)
        self.italic_menu_var = tk.BooleanVar(value=False)
        self.center_menu_var = tk.BooleanVar(value=False)
        self.createMenuBar()
        
        # window design goes here
        
        # panedwindow allows dynamic resize by user
        panedWin = ttk.PanedWindow(self.window, orient='horizontal')
        panedWin.pack(fill='both', expand=True)

        # first the file tree
        treeFrame = tk.Frame(panedWin)
        #treeFrame.grid(row=0, column=0, sticky='nsw') # not 100% fill
        panedWin.add(treeFrame)

        # browse is used because multiselect is hard, and this works fine for a tree-based text editor
        
        ttk.Style().configure('Treeview', font=self.tkinter_font) # set the font of the treeview to a known font, for horisontal scroll adjust
        
        self.tkintertree_itemid = 0


        # moving the width from a minimum width, to a starting width
        self.tree = ScrollableTreeView(treeFrame, width=230, selectmode='browse')
        self.tree.pack(anchor='w', fill='both', expand=True) # treeview is anchored to the west
        self.tree.heading('#0', text='Nodes', anchor='w') # set the default heading name and width
        self.tree.column('#0', anchor='w')

        self.node_context_menu = tk.Menu(self.window, tearoff=False)
        self.node_context_menu.add_command(label='Rename', command=self.renameNode)
        self.node_context_menu.add_command(label='Move', command=self.beginMoveNode)
        self.node_context_menu.add_command(label='Add Child', command=self.createNewNode)
        self.node_context_menu.add_separator()
        self.node_context_menu.add_command(label='Archive', command=self.archiveSelectedNode)
        self.node_context_menu.add_command(label='Delete', command=self.deleteNode)
        self.tree.bind('<Button-3>', self.showNodeContextMenu)
        self.tree.bind('<Button-1>', self.completeMoveNode, add='+')
        self.window.bind_all('<Escape>', self.cancelNodeInteraction, add='+')
        
        # bind a callback for horizontal scroll adjustment
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.actionQueue.put(PrioritizedItem(3, lambda : self.treeOpenClose(e), "treeOpenClose")))
        # Delay a single-click preview long enough to distinguish it from a
        # double-click, which explicitly opens a separate tab.
        self.tree.bind('<ButtonRelease-1>', self.scheduleNodePreview, add='+')
        self.tree.bind('<Double-1>', self.openNodeFromTreeDoubleClick)

        # bind a callback for treeview open so that lazy loading is possible
        # this is lower priority than lazyUnload so then it always will run after lazyUnload if they are both in the queue
        self.tree.bind('<<TreeviewOpen>>', lambda e: self.actionQueue.put(PrioritizedItem(2, lambda : self.lazyloadNodes(e), "lazyloadNodes")))
        # treeview close is used to help save memory on lazy-load by clearing old stuff
        self.tree.bind('<<TreeviewClose>>', lambda e: self.actionQueue.put(PrioritizedItem(1, lambda : self.lazyUnloadNodes(e), "lazyUnloadNodes")))

        # end file tree
        
        # start tabbed text area
        textFrame = tk.Frame(panedWin)
        panedWin.add(textFrame)
        self.editor_tabs = ttk.Notebook(textFrame)
        self.notebook = self.editor_tabs
        self.editor_tabs.pack(fill='both', expand=True)
        self.editor_tabs.bind('<<NotebookTabChanged>>', self.onEditorTabChanged)
        self.editor_tabs.bind('<Button-2>', self.closeTabAtEvent)
        self.editor_tabs.bind('<Button-3>', self.showTabContextMenu)

        self.tab_context_menu = tk.Menu(self.window, tearoff=False)
        self.tab_context_menu.add_command(label='Close Tab', command=self.closeCurrentTab)
        self.tab_context_menu.add_command(label='Close Other Tabs', command=self.closeOtherTabs)

        self.text_context_menu = tk.Menu(self.window, tearoff=False)
        self.text_context_menu.add_command(label='Undo', command=self.undoDocument)
        self.text_context_menu.add_command(label='Redo', command=self.redoDocument)
        self.text_context_menu.add_separator()
        self.text_context_menu.add_command(label='Cut', command=self.cutTextSelection)
        self.text_context_menu.add_command(label='Copy', command=self.copyFromClipboard)
        self.text_context_menu.add_command(label='Paste', command=self.pasteFromClipboard)

        initial_document = self.createDocumentTab()
        self.activateDocument(initial_document)
        
        # end textarea
        
        # holds the currently selected node
        self.selected_node = ()

        # holds all of the node item ids
        self.item_ids : list = []

        #self.populateNodeTree() # load nodes for file tree on startup
        # add initial load for file tree nodes on startup
        self.actionQueue.put(PrioritizedItem(0, self.populateNodeTree, "InitialPopulate"))

        # Tk widgets are not thread-safe, so queued UI work is drained from the
        # Tk event loop instead of a background thread.
        if self.start_worker:
            self._queue_after_id = self.window.after_idle(self.processActionQueueItem)
        
        if self.start_mainloop:
            self.window.mainloop()

    def bindTextEditor(self, editor):
        """Attach the document editing behavior to a tab's text widget."""
        editor.bind('<Button-3>', self.showTextContextMenu)
        editor.bind('<Control-v>', self.pasteFromClipboard)
        editor.bind('<Control-c>', self.copyFromClipboard)
        editor.bind('<Control-z>', self.undoDocument)
        editor.bind('<Control-Z>', self.undoDocument)
        editor.bind('<Control-y>', self.redoDocument)
        editor.bind('<Control-Y>', self.redoDocument)
        editor.bind('<Control-b>', lambda _: self.toggleBoldForSelection())
        editor.bind('<Control-i>', lambda _: self.toggleItalicForSelection())
        editor.bind('<Control-e>', lambda _: self.toggleCenterAlignmentForSelection())
        editor.bind('<KeyPress>', self.insertTypedTextWithCurrentStyle, add='+')
        editor.bind('<KeyRelease>', self.scheduleToolbarStyleUpdate, add='+')
        editor.bind('<KeyRelease>', self.scheduleCenteredTextLayoutRefresh, add='+')
        editor.bind('<KeyRelease>', self.scheduleTableLayoutRefresh, add='+')
        editor.bind('<ButtonRelease-1>', self.scheduleToolbarStyleUpdate, add='+')
        editor.bind('<<Selection>>', self.scheduleToolbarStyleUpdate, add='+')
        editor.bind('<Configure>', self.scheduleCenteredTextLayoutRefresh, add='+')
        editor.bind('<Configure>', self.scheduleTableLayoutRefresh, add='+')
        editor.bind('<Motion>', self.updateImageResizeCursor, add='+')
        editor.bind('<ButtonPress-1>', self.beginImageResize, add='+')
        editor.bind('<B1-Motion>', self.dragImageResize, add='+')
        editor.bind('<ButtonRelease-1>', self.finishImageResize, add='+')
        editor.bind('<Control-x>', self.cutTextSelection)
        editor.bind(
            '<<Modified>>',
            lambda _event, current_editor=editor: self.onDocumentModified(current_editor),
            add='+',
        )

    def createDocumentTab(self, path='', relative_path=''):
        editor = ScrollableText(
            self.editor_tabs,
            font=self.tkinter_font,
            cursor=self.TEXT_CURSOR,
            undo=True,
            autoseparators=True,
            maxundo=-1,
        )
        self.bindTextEditor(editor)
        tab_id = str(editor)
        document = OpenDocument(
            tab_id=tab_id,
            text=editor,
            path=path,
            relative_path=relative_path,
        )
        self.open_documents_by_tab[tab_id] = document
        if path:
            self.registerOpenDocumentPath(document)
        self.editor_tabs.add(editor, text=self.documentTabTitle(document))
        editor.edit_modified(False)
        return document

    def normalizedDocumentPath(self, path):
        if not path:
            return ''
        return os.path.normcase(os.path.abspath(os.path.normpath(path)))

    def registerOpenDocumentPath(self, document):
        if document.path:
            self.open_documents_by_path[
                self.normalizedDocumentPath(document.path)
            ] = document
        return document

    def unregisterOpenDocumentPath(self, document, path=None):
        normalized_path = self.normalizedDocumentPath(path or document.path)
        if not normalized_path:
            return None
        if self.open_documents_by_path.get(normalized_path) is not document:
            return None

        replacement = next(
            (
                candidate
                for candidate in reversed(list(self.open_documents_by_tab.values()))
                if candidate is not document
                and self.normalizedDocumentPath(candidate.path) == normalized_path
            ),
            None,
        )
        if replacement is None:
            self.open_documents_by_path.pop(normalized_path, None)
        else:
            self.open_documents_by_path[normalized_path] = replacement
        return replacement

    def documentTabTitle(self, document):
        if document.relative_path:
            title = document.relative_path.replace(os.sep, ' \u203a ')
        elif document.path:
            title = os.path.splitext(os.path.basename(document.path))[0]
        else:
            title = 'No note open'
        return f'* {title}' if document.dirty else title

    def updateDocumentTabTitle(self, document):
        try:
            self.editor_tabs.tab(document.tab_id, text=self.documentTabTitle(document))
        except tk.TclError:
            pass

    def captureActiveDocumentState(self):
        document = self.active_document
        if document is None:
            return None
        document.tkinter_imagelist = self.tkinter_imagelist
        document.embedded_images = self.embedded_images
        document.embedded_files = self.embedded_files
        document.font_table = self.font_table
        document.color_table = self.color_table
        document.style_tags = self.style_tags
        document.style_tag_names = self.style_tag_names
        document.style_tag_counter = self.style_tag_counter
        document.typing_style = self.typing_style.copy()
        document.current_text_cursor = self.current_text_cursor
        document.image_resize_state = self.image_resize_state
        if document.path:
            document.dirty = bool(document.text.edit_modified())
        self.updateDocumentTabTitle(document)
        return document

    def activateDocument(self, document, select_tab=True):
        if document is None:
            return None
        self.cancelPendingNodePreview()
        if self.active_document is not document:
            self.cancelScheduledToolbarStyleUpdate()
            self.cancelScheduledCenteredTextLayoutRefresh()
            self.cancelScheduledTableLayoutRefresh()
            self.captureActiveDocumentState()

        self.active_document = document
        self.text = document.text
        self.openFile = document.path
        self.tkinter_imagelist = document.tkinter_imagelist
        self.embedded_images = document.embedded_images
        self.embedded_files = document.embedded_files
        self.font_table = document.font_table
        self.color_table = document.color_table
        self.style_tags = document.style_tags
        self.style_tag_names = document.style_tag_names
        self.style_tag_counter = document.style_tag_counter
        self.typing_style = document.typing_style.copy()
        self.current_text_cursor = document.current_text_cursor
        self.image_resize_state = document.image_resize_state

        if select_tab and self.editor_tabs.select() != document.tab_id:
            self.editor_tabs.select(document.tab_id)
        self.setToolbarStyleVars(self.typing_style)
        self.scheduleCenteredTextLayoutRefresh()
        self.scheduleTableLayoutRefresh()
        return document

    def onEditorTabChanged(self, event=None):
        tab_id = self.editor_tabs.select()
        document = self.open_documents_by_tab.get(tab_id)
        if document is None:
            return None
        self.activateDocument(document, select_tab=False)
        if document.relative_path:
            self.selectNodePath(document.relative_path, open_document=False)
        document.text.focus_set()
        return None

    def onDocumentModified(self, editor):
        document = self.open_documents_by_tab.get(str(editor))
        if document is None:
            return None
        modified = bool(editor.edit_modified())
        if document.loading:
            if modified:
                editor.edit_modified(False)
            return None
        document.dirty = modified and bool(document.path)
        self.updateDocumentTabTitle(document)
        return None

    def markCurrentDocumentModified(self):
        document = self.active_document
        if document is None or document.loading or not document.path:
            return None
        self.text.edit_modified(True)
        document.dirty = True
        self.updateDocumentTabTitle(document)
        return None

    def selectDocumentTab(self, document):
        self.activateDocument(document)
        document.text.focus_set()
        return document

    def tabIdAtEvent(self, event):
        try:
            return self.editor_tabs.tabs()[self.editor_tabs.index(f'@{event.x},{event.y}')]
        except (tk.TclError, IndexError):
            return None

    def closeTabAtEvent(self, event):
        tab_id = self.tabIdAtEvent(event)
        if tab_id is not None:
            self.closeDocumentTab(tab_id)
        return 'break'

    def showTabContextMenu(self, event):
        tab_id = self.tabIdAtEvent(event)
        if tab_id is None:
            return None
        self.editor_tabs.select(tab_id)
        self.activateDocument(self.open_documents_by_tab.get(tab_id), select_tab=False)
        try:
            self.tab_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.tab_context_menu.grab_release()
        return 'break'

    def closeCurrentTab(self, event=None):
        tab_id = self.editor_tabs.select()
        if tab_id:
            self.closeDocumentTab(tab_id)
        return 'break'

    def closeOtherTabs(self):
        selected_tab = self.editor_tabs.select()
        for tab_id in list(self.editor_tabs.tabs()):
            if tab_id != selected_tab and not self.closeDocumentTab(tab_id):
                break
        return 'break'

    def closeDocumentTab(self, tab_id, force=False, create_placeholder=True):
        document = self.open_documents_by_tab.get(tab_id)
        if document is None:
            return True

        if document is self.active_document:
            self.captureActiveDocumentState()
        if document.dirty and not force:
            answer = messagebox.askyesnocancel(
                'Save changes?',
                f'Save changes to {self.documentTabTitle(document).lstrip("* ")} before closing?',
            )
            if answer is None:
                return False
            if answer:
                self.activateDocument(document)
                if not self.writeCurrentDocument(show_confirmation=False):
                    return False

        if document.path:
            self.unregisterOpenDocumentPath(document)
        self.open_documents_by_tab.pop(tab_id, None)
        if document is self.active_document:
            self.active_document = None
        try:
            self.editor_tabs.forget(tab_id)
            document.text.destroy()
        except tk.TclError:
            pass

        remaining_tabs = self.editor_tabs.tabs()
        if remaining_tabs:
            self.activateDocument(
                self.open_documents_by_tab.get(self.editor_tabs.select()),
                select_tab=False,
            )
        elif create_placeholder:
            self.activateDocument(self.createDocumentTab())
        return True

    def closeWindow(self):
        for tab_id in list(self.editor_tabs.tabs()):
            if not self.closeDocumentTab(tab_id, create_placeholder=False):
                return None
        self.window.destroy()
        return 'break'

    def showNodeContextMenu(self, event):
        """Select the node under the pointer and show its context menu."""
        if self.move_source_node is not None:
            self.cancelMoveNode()
            return 'break'

        node = self.tree.identify('item', event.x, event.y)
        if not node:
            return None

        self.tree.selection_set(node)
        self.tree.focus(item=node)
        self.selected_node = node

        try:
            self.node_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.node_context_menu.grab_release()

        return 'break'

    def cancelPendingNodePreview(self):
        if self.tree_single_click_after_id is not None:
            try:
                self.window.after_cancel(self.tree_single_click_after_id)
            except tk.TclError:
                pass
            self.tree_single_click_after_id = None
        return None

    def scheduleNodePreview(self, event):
        if self.ignore_next_tree_release:
            self.ignore_next_tree_release = False
            return None

        try:
            if self.tree.widget.identify_element(event.x, event.y) == 'Treeitem.indicator':
                return None
        except tk.TclError:
            return None

        node = self.tree.identify('item', event.x, event.y)
        if not node:
            return None

        self.cancelPendingNodePreview()
        self.tree_single_click_after_id = self.window.after(
            self.TREE_SINGLE_CLICK_DELAY_MS,
            lambda selected_node=node: self.previewNodeInFirstTab(selected_node),
        )
        return None

    def previewNodeInFirstTab(self, node):
        self.tree_single_click_after_id = None
        try:
            self.tree.item(node)
        except tk.TclError:
            return None

        tabs = self.editor_tabs.tabs()
        if not tabs:
            return None
        first_document = self.open_documents_by_tab.get(tabs[0])
        if first_document is None:
            return None
        self.activateDocument(first_document)

        self.tree.selection_set(node)
        self.tree.focus(item=node)
        self.selected_node = node
        return self.tryReadShowRTF(
            None,
            open_in_new_tab=False,
            reuse_open_tab=False,
        )

    def openNodeFromTreeDoubleClick(self, event):
        self.cancelPendingNodePreview()
        # The second button release belongs to this double-click and must not
        # schedule a single-click preview afterward.
        self.ignore_next_tree_release = True
        node = self.tree.identify('item', event.x, event.y)
        if not node:
            return None

        self.tree.selection_set(node)
        self.tree.focus(item=node)
        self.selected_node = node
        self.tryReadShowRTF(
            event,
            open_in_new_tab=True,
            force_new_tab=True,
        )
        return 'break'

    def showTextContextMenu(self, event):
        """Show editing actions for the document at the pointer position."""
        pointer_index = self.text.index(f'@{event.x},{event.y}')
        selection = self.text.tag_ranges('sel')
        pointer_is_selected = (
            selection
            and self.text.compare(pointer_index, '>=', 'sel.first')
            and self.text.compare(pointer_index, '<', 'sel.last')
        )

        if not pointer_is_selected:
            self.text.tag_remove('sel', '1.0', 'end')
            self.text.mark_set('insert', pointer_index)

        has_selection = bool(self.text.tag_ranges('sel'))
        selection_state = 'normal' if has_selection else 'disabled'
        self.text_context_menu.entryconfigure('Cut', state=selection_state)
        self.text_context_menu.entryconfigure('Copy', state=selection_state)
        self.text.focus_set()

        try:
            self.text_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.text_context_menu.grab_release()

        return 'break'

    def createMenuBar(self):
        menu_bar = tk.Menu(self.window)

        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label='Save', accelerator='Ctrl+S', command=self.saveRTF)
        file_menu.add_command(label='Save All', accelerator='Ctrl+Shift+S', command=self.saveAllTabs)
        file_menu.add_command(label='Close Tab', accelerator='Ctrl+W', command=self.closeCurrentTab)
        file_menu.add_separator()
        file_menu.add_command(label='Exit', command=self.closeWindow)
        menu_bar.add_cascade(label='File', menu=file_menu)

        edit_menu = tk.Menu(menu_bar, tearoff=False)
        edit_menu.add_command(label='Undo', accelerator='Ctrl+Z', command=self.undoDocument)
        edit_menu.add_command(label='Redo', accelerator='Ctrl+Y', command=self.redoDocument)
        edit_menu.add_separator()
        edit_menu.add_command(
            label='Search All Notes...',
            accelerator='Ctrl+Shift+F',
            command=self.showSearchDialog,
        )
        menu_bar.add_cascade(label='Edit', menu=edit_menu)

        node_menu = tk.Menu(menu_bar, tearoff=False)
        node_menu.add_command(label='Update', command=self.populateNodeTree)
        node_menu.add_separator()
        node_menu.add_command(label='New', command=self.createNewNode)
        node_menu.add_command(label='Rename', command=self.renameNode)
        node_menu.add_command(label='Move', command=self.beginMoveNode)
        node_menu.add_command(label='Archive', command=self.archiveSelectedNode)
        node_menu.add_command(label='Browse Archive...', command=self.showArchiveDialog)
        node_menu.add_separator()
        node_menu.add_command(label='Delete', command=self.deleteNode)
        menu_bar.add_cascade(label='Nodes', menu=node_menu)

        insert_menu = tk.Menu(menu_bar, tearoff=False)
        insert_menu.add_command(label='Table...', command=self.showInsertTableDialog)
        menu_bar.add_cascade(label='Insert', menu=insert_menu)

        format_menu = tk.Menu(menu_bar, tearoff=False)

        format_menu.add_command(label='Font Family...', command=self.showFontFamilyDialog)

        size_menu = tk.Menu(format_menu, tearoff=False)
        for size in (6, 8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 72, 96):
            size_menu.add_radiobutton(
                label=str(size),
                variable=self.font_size_var,
                value=size,
                command=self.applySelectedFontSize,
            )
        size_menu.add_separator()
        size_menu.add_command(label='Custom...', command=self.askForFontSize)
        format_menu.add_cascade(label='Font Size', menu=size_menu)

        format_menu.add_command(label='Text Color...', command=self.chooseTextColorForSelection)
        format_menu.add_separator()
        format_menu.add_checkbutton(
            label='Bold',
            accelerator='Ctrl+B',
            variable=self.bold_menu_var,
            command=self.toggleBoldForSelection,
        )
        format_menu.add_checkbutton(
            label='Italic',
            accelerator='Ctrl+I',
            variable=self.italic_menu_var,
            command=self.toggleItalicForSelection,
        )
        format_menu.add_checkbutton(
            label='Centered Text',
            accelerator='Ctrl+E',
            variable=self.center_menu_var,
            command=self.applyCenterAlignmentFromMenu,
        )
        menu_bar.add_cascade(label='Format', menu=format_menu)

        self.window.config(menu=menu_bar)
        self.window.bind_all('<Control-s>', self.saveRTFShortcut)
        self.window.bind_all('<Control-Shift-s>', self.saveAllTabs)
        self.window.bind_all('<Control-Shift-S>', self.saveAllTabs)
        self.window.bind_all('<Control-w>', self.closeCurrentTab)
        self.window.bind_all('<Control-W>', self.closeCurrentTab)
        self.window.bind_all('<Control-Shift-f>', self.showSearchDialog)
        self.window.bind_all('<Control-Shift-F>', self.showSearchDialog)

    def showSearchDialog(self, event=None):
        if self.search_popup is not None:
            try:
                self.search_popup.lift()
                self.search_entry.focus_set()
                return 'break'
            except tk.TclError:
                self.search_popup = None

        popup = self.search_popup = tk.Toplevel(self.window)
        popup.title('Search All Notes')
        popup.geometry('820x460')
        popup.transient(self.window)
        popup.protocol('WM_DELETE_WINDOW', self.closeSearchDialog)
        popup.grid_columnconfigure(0, weight=1)
        popup.grid_rowconfigure(1, weight=1)

        search_frame = ttk.Frame(popup, padding=(10, 10, 10, 6))
        search_frame.grid(row=0, column=0, sticky='ew')
        search_frame.grid_columnconfigure(0, weight=1)

        self.search_query_var = tk.StringVar()
        self.search_entry = ttk.Entry(
            search_frame,
            textvariable=self.search_query_var,
        )
        self.search_entry.grid(row=0, column=0, sticky='ew', padx=(0, 8))
        self.search_button = ttk.Button(
            search_frame,
            text='Search',
            command=self.startNoteSearch,
        )
        self.search_button.grid(row=0, column=1)

        results_frame = ttk.Frame(popup, padding=(10, 0, 10, 6))
        results_frame.grid(row=1, column=0, sticky='nsew')
        results_frame.grid_columnconfigure(0, weight=1)
        results_frame.grid_rowconfigure(0, weight=1)

        self.search_results_tree = ttk.Treeview(
            results_frame,
            columns=('node', 'context'),
            show='headings',
            selectmode='browse',
        )
        self.search_results_tree.heading('node', text='Node')
        self.search_results_tree.heading('context', text='Matching text')
        self.search_results_tree.column('node', width=240, stretch=False)
        self.search_results_tree.column('context', width=520, stretch=True)
        self.search_results_tree.grid(row=0, column=0, sticky='nsew')
        result_scrollbar = ttk.Scrollbar(
            results_frame,
            orient='vertical',
            command=self.search_results_tree.yview,
        )
        result_scrollbar.grid(row=0, column=1, sticky='ns')
        self.search_results_tree.configure(yscrollcommand=result_scrollbar.set)
        self.search_results_tree.bind(
            '<Double-1>',
            lambda _event: self.openSelectedSearchResult(),
        )
        self.search_results_tree.bind(
            '<Return>',
            lambda _event: self.openSelectedSearchResult(),
        )

        footer = ttk.Frame(popup, padding=(10, 0, 10, 10))
        footer.grid(row=2, column=0, sticky='ew')
        footer.grid_columnconfigure(0, weight=1)
        self.search_status_var = tk.StringVar(
            value='Enter text to search every saved note.'
        )
        ttk.Label(footer, textvariable=self.search_status_var).grid(
            row=0,
            column=0,
            sticky='w',
        )
        ttk.Button(
            footer,
            text='Open',
            command=self.openSelectedSearchResult,
        ).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(
            footer,
            text='Close',
            command=self.closeSearchDialog,
        ).grid(row=0, column=2, padx=(8, 0))

        self.search_entry.bind('<Return>', lambda _event: self.startNoteSearch())
        self.search_entry.focus_set()
        return 'break'

    def closeSearchDialog(self):
        self.search_generation += 1
        popup = self.search_popup
        self.search_popup = None
        self.search_results = {}
        if popup is not None:
            popup.destroy()

    def startNoteSearch(self):
        query = self.search_query_var.get()
        if not query:
            self.search_status_var.set('Enter text to search every saved note.')
            return None

        self.search_generation += 1
        generation = self.search_generation
        self.search_button.configure(state='disabled')
        self.search_status_var.set('Updating the index and searching\u2026')
        for item in self.search_results_tree.get_children():
            self.search_results_tree.delete(item)
        self.search_results = {}

        worker = threading.Thread(
            target=self._runNoteSearch,
            args=(query, generation),
            daemon=True,
        )
        worker.start()
        return 'break'

    def _runNoteSearch(self, query, generation):
        try:
            stats, results = self.search_index.refresh_and_search(query)
            error = None
        except Exception as exc:
            stats, results = None, []
            error = str(exc)

        # Tk calls must stay on the event-loop thread. The app's existing
        # priority queue is polled there, while indexing remains off-thread.
        self.actionQueue.put(
            PrioritizedItem(
                0,
                lambda: self._showNoteSearchResults(
                    query,
                    generation,
                    stats,
                    results,
                    error,
                ),
                "showNoteSearchResults",
            )
        )

    def _showNoteSearchResults(self, query, generation, stats, results, error):
        if generation != self.search_generation or self.search_popup is None:
            return None

        self.search_button.configure(state='normal')
        if error is not None:
            self.search_status_var.set(f'Search failed: {error}')
            return None

        for result in results:
            item = self.search_results_tree.insert(
                '',
                'end',
                values=(result.path, result.snippet),
            )
            self.search_results[item] = result.path

        count = len(results)
        suffix = '' if count != 200 else ' (first 200)'
        indexed = stats['updated']
        index_note = f' Indexed {indexed} changed note(s).' if indexed else ''
        self.search_status_var.set(
            f'{count} match(es) for \u201c{query}\u201d{suffix}.{index_note}'
        )
        if results:
            first = self.search_results_tree.get_children()[0]
            self.search_results_tree.selection_set(first)
            self.search_results_tree.focus(first)
        return None

    def openSelectedSearchResult(self):
        selection = self.search_results_tree.selection()
        if not selection:
            return None
        path = self.search_results.get(selection[0])
        if path is not None:
            self.selectNodePath(path)
        return 'break'

    def showArchiveDialog(self):
        if self.archive_popup is not None:
            try:
                self.archive_popup.lift()
                self.archive_search_entry.focus_set()
                return 'break'
            except tk.TclError:
                self.archive_popup = None

        popup = self.archive_popup = tk.Toplevel(self.window)
        popup.title('Archived Notes')
        popup.geometry('980x500')
        popup.transient(self.window)
        popup.protocol('WM_DELETE_WINDOW', self.closeArchiveDialog)
        popup.grid_columnconfigure(0, weight=1)
        popup.grid_rowconfigure(1, weight=1)

        search_frame = ttk.Frame(popup, padding=(10, 10, 10, 6))
        search_frame.grid(row=0, column=0, sticky='ew')
        search_frame.grid_columnconfigure(0, weight=1)
        self.archive_query_var = tk.StringVar()
        self.archive_search_entry = ttk.Entry(
            search_frame,
            textvariable=self.archive_query_var,
        )
        self.archive_search_entry.grid(row=0, column=0, sticky='ew', padx=(0, 8))
        self.archive_search_button = ttk.Button(
            search_frame,
            text='Search Archive',
            command=self.startArchiveSearch,
        )
        self.archive_search_button.grid(row=0, column=1)

        results_frame = ttk.Frame(popup, padding=(10, 0, 10, 6))
        results_frame.grid(row=1, column=0, sticky='nsew')
        results_frame.grid_columnconfigure(0, weight=1)
        results_frame.grid_rowconfigure(0, weight=1)
        self.archive_results_tree = ttk.Treeview(
            results_frame,
            columns=('note', 'archived_root', 'archived_at', 'context'),
            show='headings',
            selectmode='browse',
        )
        self.archive_results_tree.heading('note', text='Archived note')
        self.archive_results_tree.heading('archived_root', text='Restore bundle')
        self.archive_results_tree.heading('archived_at', text='Archived')
        self.archive_results_tree.heading('context', text='Matching text')
        self.archive_results_tree.column('note', width=220, stretch=False)
        self.archive_results_tree.column('archived_root', width=180, stretch=False)
        self.archive_results_tree.column('archived_at', width=170, stretch=False)
        self.archive_results_tree.column('context', width=360, stretch=True)
        self.archive_results_tree.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(
            results_frame,
            orient='vertical',
            command=self.archive_results_tree.yview,
        )
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.archive_results_tree.configure(yscrollcommand=scrollbar.set)
        self.archive_results_tree.bind(
            '<Double-1>',
            lambda _event: self.restoreSelectedArchive(),
        )
        self.archive_results_tree.bind(
            '<Return>',
            lambda _event: self.restoreSelectedArchive(),
        )

        footer = ttk.Frame(popup, padding=(10, 0, 10, 10))
        footer.grid(row=2, column=0, sticky='ew')
        footer.grid_columnconfigure(0, weight=1)
        self.archive_status_var = tk.StringVar(
            value='Loading archived notes\u2026'
        )
        ttk.Label(footer, textvariable=self.archive_status_var).grid(
            row=0,
            column=0,
            sticky='w',
        )
        ttk.Button(
            footer,
            text='Restore Bundle',
            command=self.restoreSelectedArchive,
        ).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(
            footer,
            text='Close',
            command=self.closeArchiveDialog,
        ).grid(row=0, column=2, padx=(8, 0))

        self.archive_search_entry.bind(
            '<Return>',
            lambda _event: self.startArchiveSearch(),
        )
        self.archive_search_entry.focus_set()
        self.startArchiveSearch()
        return 'break'

    def closeArchiveDialog(self):
        self.archive_generation += 1
        popup = self.archive_popup
        self.archive_popup = None
        self.archive_results = {}
        if popup is not None:
            popup.destroy()

    def startArchiveSearch(self):
        query = self.archive_query_var.get()
        self.archive_generation += 1
        generation = self.archive_generation
        self.archive_search_button.configure(state='disabled')
        self.archive_status_var.set('Searching compressed archives\u2026')
        for item in self.archive_results_tree.get_children():
            self.archive_results_tree.delete(item)
        self.archive_results = {}

        worker = threading.Thread(
            target=self._runArchiveSearch,
            args=(query, generation),
            daemon=True,
        )
        worker.start()
        return 'break'

    def _runArchiveSearch(self, query, generation):
        try:
            results = self.archive_store.search(query)
            error = None
        except Exception as exc:
            results = []
            error = str(exc)
        self.actionQueue.put(
            PrioritizedItem(
                0,
                lambda: self._showArchiveSearchResults(
                    query,
                    generation,
                    results,
                    error,
                ),
                "showArchiveSearchResults",
            )
        )

    def _showArchiveSearchResults(self, query, generation, results, error):
        if generation != self.archive_generation or self.archive_popup is None:
            return None
        self.archive_search_button.configure(state='normal')
        if error is not None:
            self.archive_status_var.set(f'Archive search failed: {error}')
            return None

        for result in results:
            archived_at = result.archived_at.replace('T', ' ')[:19] + ' UTC'
            item = self.archive_results_tree.insert(
                '',
                'end',
                values=(
                    result.note_path,
                    result.archived_path,
                    archived_at,
                    result.snippet,
                ),
            )
            self.archive_results[item] = result.archive_id

        count = len(results)
        suffix = '' if count != 200 else ' (first 200)'
        if query:
            status = f'{count} archived match(es) for \u201c{query}\u201d{suffix}.'
        else:
            status = f'{count} archived note(s){suffix}.'
        self.archive_status_var.set(status)
        if results:
            first = self.archive_results_tree.get_children()[0]
            self.archive_results_tree.selection_set(first)
            self.archive_results_tree.focus(first)
        return None

    def restoreSelectedArchive(self):
        selection = self.archive_results_tree.selection()
        if not selection:
            return None
        archive_id = self.archive_results.get(selection[0])
        if archive_id is None:
            return None
        values = self.archive_results_tree.item(selection[0], 'values')
        archived_root = values[1]
        if not messagebox.askyesno(
            'Restore archived notes?',
            f'Restore "{archived_root}" and all notes archived with it?',
        ):
            return None
        try:
            restored_path = self.archive_store.restore(archive_id)
        except ArchiveConflictError as exc:
            messagebox.showerror('Restore conflict', str(exc))
            return None
        except (ArchiveError, OSError) as exc:
            messagebox.showerror('Restore failed', str(exc))
            return None

        self.populateNodeTree()
        self.selectNodePath(restored_path, open_document=False)
        self.startArchiveSearch()
        messagebox.showinfo(
            'Archive restored',
            f'Restored "{restored_path}" to the active notebook.',
        )
        return 'break'

    def selectNodePath(self, relative_path, open_document=True):
        """Expand lazy tree levels and select a note by its relative path."""
        normalized_path = os.path.normpath(relative_path)
        if normalized_path in ('', '.'):
            return None

        segments = normalized_path.split(os.sep)
        parent = ''
        accumulated = []
        for segment in segments:
            children = {
                self.tree.item(child)['text']: child
                for child in self.tree.get_children(parent)
            }
            if segment not in children:
                parent_path = os.path.join(*accumulated) if accumulated else ''
                full_parent_path = (
                    self.resolveNodePath(parent_path)
                    if parent_path
                    else self._node_root_path()
                )
                self.populateNodeTree(full_parent_path, parent)
                children = {
                    self.tree.item(child)['text']: child
                    for child in self.tree.get_children(parent)
                }
            if segment not in children:
                return None
            parent = children[segment]
            accumulated.append(segment)
            if segment != segments[-1]:
                self.tree.item(parent, open=True)

        self.tree.selection_set(parent)
        self.tree.focus(parent)
        self.tree.see(parent)
        self.selected_node = parent
        if open_document:
            self.tryReadShowRTF(None)
        return parent
    
    def LogWithDateTime(self, *strstolog : str):
        print(datetime.datetime.now(), ':', *strstolog)

    def saveRTFShortcut(self, event=None):
        self.saveRTF()
        return 'break'

    def undoDocument(self, event=None):
        """Undo the most recent edit in the current document."""
        try:
            self.text.edit_undo()
        except tk.TclError:
            pass
        self.scheduleToolbarStyleUpdate()
        self.scheduleCenteredTextLayoutRefresh()
        self.scheduleTableLayoutRefresh()
        return 'break'

    def redoDocument(self, event=None):
        """Redo the most recently undone edit in the current document."""
        try:
            self.text.edit_redo()
        except tk.TclError:
            pass
        self.scheduleToolbarStyleUpdate()
        self.scheduleCenteredTextLayoutRefresh()
        self.scheduleTableLayoutRefresh()
        return 'break'

    def showFontFamilyDialog(self):
        if self.UI_popup is not None:
            self.UI_popup.lift()
            return None

        self.UI_popup = (fontWin := tk.Toplevel(self.window))
        fontWin.title('Font Family')
        fontWin.geometry('320x420')
        fontWin.minsize(240, 260)
        fontWin.wm_protocol('WM_DELETE_WINDOW', self.killUIPopup)
        fontWin.grid_rowconfigure(0, weight=1)
        fontWin.grid_columnconfigure(0, weight=1)

        listFrame = tk.Frame(fontWin)
        listFrame.grid(row=0, column=0, sticky='nsew', padx=8, pady=(8, 4))
        listFrame.grid_rowconfigure(0, weight=1)
        listFrame.grid_columnconfigure(0, weight=1)

        fontList = tk.Listbox(listFrame, exportselection=False)
        fontList.grid(row=0, column=0, sticky='nsew')

        scrollbar = tk.Scrollbar(listFrame, orient='vertical', command=fontList.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        fontList.configure(yscrollcommand=scrollbar.set)

        for family in self.font_values:
            fontList.insert('end', family)

        current_family = self.font_family_var.get()
        if current_family in self.font_values:
            current_index = self.font_values.index(current_family)
            fontList.selection_set(current_index)
            fontList.activate(current_index)
            fontList.see(current_index)

        buttonFrame = tk.Frame(fontWin)
        buttonFrame.grid(row=1, column=0, sticky='ew', padx=8, pady=(4, 8))

        def applyFontFamily():
            selection = fontList.curselection()
            if len(selection) == 0:
                return None

            self.font_family_var.set(fontList.get(selection[0]))
            result = self.applySelectedFontFamily()
            self.killUIPopup()
            return result

        tk.Button(buttonFrame, text='Apply', command=applyFontFamily).pack(side='right')
        tk.Button(buttonFrame, text='Cancel', command=self.killUIPopup).pack(side='right', padx=(0, 6))

        fontList.bind('<Double-1>', lambda _: applyFontFamily())
        fontList.bind('<Return>', lambda _: applyFontFamily())
        fontList.focus_set()

        return None

    def getNextTkinterItemId(self):
        # from 0 to the max item id
        for i in range(len(self.item_ids)):
            if self.item_ids[i] != i: # found an open item id
                self.item_ids.insert(i, i)
                return f'ITEM_{i}'
        # this is if a new itemid should be added
        self.item_ids += [len(self.item_ids)]
        return f'ITEM_{self.item_ids[-1]}'

    def processActionQueueItem(self):
        try:
            if not self.actionQueue.empty():
                print('')
            while not self.actionQueue.empty():
                itemToRun : PrioritizedItem = cast(PrioritizedItem, self.actionQueue.get_nowait())
                try:
                    self.LogWithDateTime(itemToRun.priority, itemToRun.descr, self.selected_node)
                    itemToRun.item()
                finally:
                    self.actionQueue.task_done()
        finally:
            self._scheduleActionQueueProcessing()

    def _scheduleActionQueueProcessing(self):
        if not self.start_worker:
            return

        try:
            if self.window.winfo_exists():
                self._queue_after_id = self.window.after(
                    self.ACTION_QUEUE_POLL_MS,
                    self.processActionQueueItem,
                )
        except tk.TclError:
            self._queue_after_id = None

    def _node_root_path(self):
        return os.path.abspath(os.path.normpath(self.nodeDir))

    def resolveNodePath(self, relative_path):
        root = self._node_root_path()
        candidate = os.path.abspath(os.path.normpath(os.path.join(root, relative_path)))

        try:
            common_path = os.path.commonpath([root, candidate])
        except ValueError as exc:
            raise ValueError("Node path must stay inside the node directory") from exc

        if os.path.normcase(common_path) != os.path.normcase(root):
            raise ValueError("Node path must stay inside the node directory")

        return candidate
        

    def getNodePathLength(self, node):
        split_parts = self.get_node_path(node).split(os.sep)
        cur_name = split_parts[-1]
        split_parts = split_parts[:-1]
        tree_item_padding = (len(split_parts) + 1) * 20 # I use 20 here because tkinter arbitrarily choses that as the padding for the treeview
        item_width = self.tkinter_font.measure(cur_name) + tree_item_padding + 5 # 5 is to give the scrollbar more breathing room
        return item_width
    
    def lazyloadNodes(self, event):
        selected_node = self.selected_node = self.tree.selection()[0] if len(self.tree.selection()) != 0 else ()
        if len(selected_node) == 0: # if nothing is selected
            return None

        path = self.get_node_path(selected_node)
        newpath = os.path.join(self.nodeDir, path)
        newpath = os.path.normpath(newpath) + os.sep
        self.populateNodeTree(newpath, selected_node)

    def get_all_children(self, anode):
        all_children = self.tree.get_children(anode)
        for child in all_children:
            all_children += self.get_all_children(child)
        
        return all_children

    # lazy unloading counterpart, for saving memory on large notebooks
    def lazyUnloadNodes(self, event):
        selected_node = self.selected_node = self.tree.selection()[0] if len(self.tree.selection()) != 0 else ()
        if len(selected_node) == 0: # if nothing is selected
            return None
        
        # do the children so dropdown is still there
        for child in self.tree.get_children(selected_node):
            children_of_child = self.get_all_children(child)
            for c in children_of_child:
                self.item_ids.remove(int(c.split('_')[1]))
            self.tree.delete(*self.tree.get_children(child)) # clear tree from unloading node

    # go through the entire tree, finding the longest element in it
    # only recurse in "open" entries of the treeview, which will also save performance
    def visit_whole_tree(self, node):
        biggest_width = self.getNodePathLength(node)
        
        for n in self.tree.get_children(node):
            if self.tree.item(n, 'open'):
                biggest_child_width = self.visit_whole_tree(n)
                if biggest_width < biggest_child_width:
                    biggest_width = biggest_child_width
            else:
                item_width = self.getNodePathLength(n)
                if biggest_width < item_width:
                    biggest_width = item_width
        
        return biggest_width
    
    def treeOpenClose(self, event):
        self.selected_node = self.tree.selection()[0] if len(self.tree.selection()) != 0 else ()
        biggest_node_width = self.visit_whole_tree('')
        # set the treeview tree column to the width of the biggest entry
        # do not stretch so the tree is forced to expand the column outside its maximum width of the frame
        # which gives a horizontal scrollbar
        self.tree.column('#0', width=biggest_node_width if biggest_node_width > 45 else 45, stretch=False)

    def defaultTextStyle(self):
        return {
            "font_family": self.DEFAULT_FONT_FAMILY,
            "font_size": self.DEFAULT_FONT_SIZE,
            "color": self.DEFAULT_TEXT_COLOR,
            "bold": False,
            "italic": False,
            "alignment": "left",
        }

    def normalizeAlignment(self, alignment):
        if alignment == "center":
            return "center"
        return "left"

    def normalizeColor(self, color):
        if color in (None, "", "default"):
            return self.DEFAULT_TEXT_COLOR

        color = color.strip()
        if re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            return color.lower()

        try:
            red, green, blue = self.window.winfo_rgb(color)
        except tk.TclError:
            return self.DEFAULT_TEXT_COLOR

        return f"#{red // 256:02x}{green // 256:02x}{blue // 256:02x}"

    def _style_key(self, style):
        return (
            style.get("font_family", self.DEFAULT_FONT_FAMILY),
            int(style.get("font_size", self.DEFAULT_FONT_SIZE)),
            self.normalizeColor(style.get("color", self.DEFAULT_TEXT_COLOR)),
            bool(style.get("bold", False)),
            bool(style.get("italic", False)),
            self.normalizeAlignment(style.get("alignment", "left")),
        )

    def getStyleTag(self, style):
        key = self._style_key(style)
        if key == self._style_key(self.defaultTextStyle()):
            return None

        if key in self.style_tag_names:
            return self.style_tag_names[key]

        tag = f"{self.FORMAT_TAG_PREFIX}{self.style_tag_counter}"
        self.style_tag_counter += 1
        self.style_tag_names[key] = tag
        self.style_tags[tag] = {
            "font_family": key[0],
            "font_size": key[1],
            "color": key[2],
            "bold": key[3],
            "italic": key[4],
            "alignment": key[5],
        }

        font_style_parts = []
        if key[3]:
            font_style_parts.append("bold")
        if key[4]:
            font_style_parts.append("italic")

        if font_style_parts:
            tag_options = {"font": (key[0], key[1], " ".join(font_style_parts))}
        else:
            tag_options = {"font": (key[0], key[1])}

        if key[2] is not None:
            tag_options["foreground"] = key[2]
        self.text.tag_configure(tag, **tag_options)

        return tag

    def getTextStyleAt(self, index):
        style = self.defaultTextStyle()
        for tag in self.text.tag_names(index):
            if tag in self.style_tags:
                style.update(self.style_tags[tag])
        return style

    def indexHasAlignmentPadding(self, index):
        return any(
            self.isAlignmentPaddingTag(tag)
            for tag in self.text.tag_names(index)
        )

    def nextNonPaddingIndex(self, index):
        current = self.text.index(index)
        line_end = self.text.index(f'{current} lineend')
        while self.text.compare(current, '<', line_end):
            if not self.indexHasAlignmentPadding(current):
                return current
            current = self.text.index(f'{current}+1c')
        return self.text.index(index)

    def getToolbarStyleIndex(self):
        if self.text.tag_ranges('sel'):
            return self.text.index('sel.first')

        index = self.text.index('insert')
        if self.text.compare(index, '==', f'{index} linestart'):
            return self.nextNonPaddingIndex(index)

        if self.text.compare(index, '>', '1.0'):
            previous_index = self.text.index(f'{index}-1c')
            if self.indexHasAlignmentPadding(previous_index):
                return self.nextNonPaddingIndex(index)
            index = previous_index
        elif self.text.compare(index, '>=', 'end'):
            index = self.text.index('end-1c')

        if self.indexHasAlignmentPadding(index):
            return self.nextNonPaddingIndex(index)

        return index

    def setToolbarStyleVars(self, style):
        self.font_family_var.set(style["font_family"])
        self.font_size_var.set(style["font_size"])
        self.bold_menu_var.set(style["bold"])
        self.italic_menu_var.set(style["italic"])
        self.center_menu_var.set(style["alignment"] == "center")

    def setTypingStyleProperty(self, property_name, value):
        self.typing_style = {**self.defaultTextStyle(), **self.typing_style}
        self.typing_style[property_name] = value
        if property_name == "color":
            self.typing_style[property_name] = self.normalizeColor(value)
        elif property_name == "alignment":
            self.typing_style[property_name] = self.normalizeAlignment(value)

        self.setToolbarStyleVars(self.typing_style)
        return 'break'

    def textStyleFont(self, style):
        font_style_parts = []
        if style.get("bold", False):
            font_style_parts.append("bold")
        if style.get("italic", False):
            font_style_parts.append("italic")

        font_args = (
            style.get("font_family", self.DEFAULT_FONT_FAMILY),
            int(style.get("font_size", self.DEFAULT_FONT_SIZE)),
        )
        if font_style_parts:
            font_args += (" ".join(font_style_parts),)

        return font.Font(font=font_args)

    def centeredLineContentWidth(self, line_start, line_end):
        width = 0
        current = line_start
        font_cache = {}
        while self.text.compare(current, '<', line_end):
            next_index = self.text.index(f'{current}+1c')
            if self.indexHasAlignmentPadding(current):
                current = next_index
                continue

            char = self.text.get(current, next_index)
            style = self.getTextStyleAt(current)
            key = self._style_key(style)
            if key not in font_cache:
                font_cache[key] = self.textStyleFont(style)
            width += font_cache[key].measure(char)
            current = next_index
        return width

    def centeredLinePadding(self, line_start, line_end, text_width):
        content_width = self.centeredLineContentWidth(line_start, line_end)
        space_width = max(1, self.tkinter_font.measure(' '))
        padding_width = max(0, (text_width - content_width) // 2)
        return ' ' * (padding_width // space_width)

    def lineHasCenteredText(self, line_start, line_end):
        current = line_start
        while self.text.compare(current, '<', line_end):
            if self.getTextStyleAt(current).get("alignment") == "center":
                return True
            current = self.text.index(f'{current}+1c')
        return False

    def hasCenteredStyleRanges(self):
        return any(
            style.get("alignment") == "center" and self.text.tag_ranges(tag)
            for tag, style in self.style_tags.items()
        )

    def isAlignmentPaddingTag(self, tag):
        return tag.startswith(self.ALIGNMENT_TAG_PREFIX)

    def removeCenteredTextPadding(self):
        for tag in list(self.text.tag_names()):
            if not self.isAlignmentPaddingTag(tag):
                continue

            ranges = list(self.text.tag_ranges(tag))
            for start, finish in reversed(list(zip(ranges[0::2], ranges[1::2]))):
                self.text.delete(start, finish)
            self.text.tag_remove(tag, '1.0', 'end')

    def centeredLinePaddingRange(self, line_start):
        for tag in self.text.tag_names(line_start):
            if not self.isAlignmentPaddingTag(tag):
                continue

            ranges = list(self.text.tag_ranges(tag))
            if len(ranges) >= 2:
                return tag, ranges[0], ranges[1]

        return None, None, None

    def removeCenteredLinePadding(self, line_start):
        tag, start, finish = self.centeredLinePaddingRange(line_start)
        if tag is None:
            return None

        self.text.delete(start, finish)
        self.text.tag_remove(tag, '1.0', 'end')
        return None

    def setCenteredLinePadding(self, line_start, padding, tag):
        existing_tag, start, finish = self.centeredLinePaddingRange(line_start)
        existing_padding = ''
        if existing_tag is not None:
            existing_padding = self.text.get(start, finish)

        if existing_padding == padding:
            return None

        if existing_tag is not None:
            self.text.delete(start, finish)
            self.text.tag_remove(existing_tag, '1.0', 'end')

        if len(padding) == 0:
            return None

        self.text.insert(line_start, padding)
        self.text.tag_add(tag, line_start, f'{line_start}+{len(padding)}c')
        for style_tag in list(self.style_tags):
            self.text.tag_remove(style_tag, line_start, f'{line_start}+{len(padding)}c')

        return None

    def scheduleCenteredTextLayoutRefresh(self, event=None):
        if self.center_layout_after_id is None:
            self.center_layout_after_id = self.window.after_idle(
                self.runScheduledCenteredTextLayoutRefresh
            )
        return None

    def cancelScheduledCenteredTextLayoutRefresh(self, event=None):
        if self.center_layout_after_id is not None:
            try:
                self.window.after_cancel(self.center_layout_after_id)
            except tk.TclError:
                pass
            self.center_layout_after_id = None

        return None

    def runScheduledCenteredTextLayoutRefresh(self):
        self.center_layout_after_id = None
        return self.refreshCenteredTextLayout()

    def refreshCenteredTextLayout(self):
        self.cancelScheduledCenteredTextLayoutRefresh()
        was_modified = bool(self.text.edit_modified())

        if not self.hasCenteredStyleRanges():
            self.removeCenteredTextPadding()
            self.text.edit_modified(was_modified)
            return None

        self.text.update_idletasks()
        text_width = max(1, self.text.winfo_width() - 6)
        last_line = int(self.text.index('end-1c').split('.')[0])
        refreshed_padding_tags = set()

        for line_number in range(1, last_line + 1):
            line_start = f'{line_number}.0'
            line_end = f'{line_number}.end'
            if not self.lineHasCenteredText(line_start, line_end):
                self.removeCenteredLinePadding(line_start)
                continue

            padding = self.centeredLinePadding(line_start, line_end, text_width)
            tag = f'{self.ALIGNMENT_TAG_PREFIX}{line_number}'
            refreshed_padding_tags.add(tag)
            self.setCenteredLinePadding(line_start, padding, tag)

        for tag in list(self.text.tag_names()):
            if self.isAlignmentPaddingTag(tag) and tag not in refreshed_padding_tags:
                ranges = list(self.text.tag_ranges(tag))
                for start, finish in reversed(list(zip(ranges[0::2], ranges[1::2]))):
                    self.text.delete(start, finish)
                self.text.tag_remove(tag, '1.0', 'end')

        self.text.edit_modified(was_modified)
        return None

    def scheduleToolbarStyleUpdate(self, event=None):
        if self.toolbar_style_after_id is None:
            self.toolbar_style_after_id = self.window.after_idle(
                self.runScheduledToolbarStyleUpdate
            )
        return None

    def cancelScheduledToolbarStyleUpdate(self, event=None):
        if self.toolbar_style_after_id is not None:
            try:
                self.window.after_cancel(self.toolbar_style_after_id)
            except tk.TclError:
                pass
            self.toolbar_style_after_id = None
        return None

    def runScheduledToolbarStyleUpdate(self):
        self.toolbar_style_after_id = None
        return self.updateToolbarStyleFromSelection()

    def updateToolbarStyleFromSelection(self):
        style = self.getTextStyleAt(self.getToolbarStyleIndex())
        self.typing_style = style.copy()

        self.setToolbarStyleVars(style)

        return None

    def insertStyledText(self, index, text, style):
        tag = self.getStyleTag(style)
        if tag is None:
            self.text.insert(index, text)
        else:
            self.text.insert(index, text, (tag,))
        self.scheduleCenteredTextLayoutRefresh()
        self.scheduleTableLayoutRefresh()

    def typedCharacterFromEvent(self, event):
        if event.state & 0x4:
            return None

        if event.keysym == 'Return':
            return '\n'

        if event.keysym == 'Tab':
            return '\t'

        if len(event.char) == 0 or ord(event.char[0]) < 32:
            return None

        return event.char

    def insertTypedText(self, text):
        if self.text.tag_ranges('sel'):
            self.text.delete('sel.first', 'sel.last')

        self.insertStyledText('insert', text, self.typing_style)
        self.text.see('insert')
        self.updateToolbarStyleFromSelection()
        return 'break'

    def insertTypedTextWithCurrentStyle(self, event):
        text = self.typedCharacterFromEvent(event)
        if text is None:
            return None

        return self.insertTypedText(text)

    def removeStyleTags(self, start, finish):
        for tag in list(self.style_tags):
            self.text.tag_remove(tag, start, finish)

    def selectedTextRange(self, show_error=True):
        if not self.text.tag_ranges('sel'):
            if show_error:
                messagebox.showerror('No text selected', 'Select text before applying formatting')
            return None

        return self.text.index('sel.first'), self.text.index('sel.last')

    def applyStylePropertyToRange(self, start, finish, property_name, value):
        current = start
        while self.text.compare(current, '<', finish):
            next_index = self.text.index(f'{current}+1c')
            style = self.getTextStyleAt(current)
            style[property_name] = value
            self.removeStyleTags(current, next_index)
            tag = self.getStyleTag(style)
            if tag is not None:
                self.text.tag_add(tag, current, next_index)
            current = next_index

        self.markCurrentDocumentModified()
        self.scheduleCenteredTextLayoutRefresh()
        self.scheduleTableLayoutRefresh()
        return 'break'

    def applyStylePropertyToSelection(self, property_name, value):
        selected_range = self.selectedTextRange(show_error=False)
        if selected_range is None:
            return self.setTypingStyleProperty(property_name, value)

        result = self.applyStylePropertyToRange(
            selected_range[0],
            selected_range[1],
            property_name,
            value,
        )
        self.updateToolbarStyleFromSelection()
        return result

    def selectionAllHasStyleProperty(self, start, finish, property_name, value):
        current = start
        while self.text.compare(current, '<', finish):
            if self.getTextStyleAt(current).get(property_name) != value:
                return False
            current = self.text.index(f'{current}+1c')

        return True

    def selectionLineRanges(self, start, finish):
        last = finish
        if self.text.compare(last, '>', start) and self.text.compare(
            last,
            '==',
            f'{last} linestart',
        ):
            last = self.text.index(f'{last}-1c')

        line_number = int(self.text.index(f'{start} linestart').split('.')[0])
        last_line_number = int(self.text.index(f'{last} linestart').split('.')[0])
        return [
            (f'{line}.0', f'{line}.end')
            for line in range(line_number, last_line_number + 1)
        ]

    def lineRangesAllHaveStyleProperty(self, line_ranges, property_name, value):
        for line_start, line_end in line_ranges:
            if self.text.compare(line_start, '==', line_end):
                return False
            if not self.selectionAllHasStyleProperty(
                line_start,
                line_end,
                property_name,
                value,
            ):
                return False
        return True

    def toggleStylePropertyForSelection(self, property_name):
        selected_range = self.selectedTextRange(show_error=False)
        if selected_range is None:
            new_value = not bool(self.typing_style.get(property_name, False))
            return self.setTypingStyleProperty(property_name, new_value)

        start, finish = selected_range
        new_value = not self.selectionAllHasStyleProperty(
            start,
            finish,
            property_name,
            True,
        )
        result = self.applyStylePropertyToRange(start, finish, property_name, new_value)
        self.updateToolbarStyleFromSelection()
        return result

    def toggleBoldForSelection(self):
        return self.toggleStylePropertyForSelection("bold")

    def toggleItalicForSelection(self):
        return self.toggleStylePropertyForSelection("italic")

    def applyCenterAlignmentFromMenu(self):
        alignment = "center" if self.center_menu_var.get() else "left"
        return self.toggleCenterAlignmentForSelection(alignment)

    def toggleCenterAlignmentForSelection(self, alignment=None):
        requested_alignment = (
            None
            if alignment is None
            else self.normalizeAlignment(alignment)
        )
        selected_range = self.selectedTextRange(show_error=False)
        if selected_range is None:
            current = self.text.index('insert')
            target_line_number = int(self.text.index(f'{current} linestart').split('.')[0])
            self.removeCenteredTextPadding()
            last_line = int(self.text.index('end-1c').split('.')[0])
            target_line_number = min(target_line_number, last_line)
            current = self.text.index(f'{target_line_number}.0')
            line_start = self.text.index(f'{current} linestart')
            line_end = self.text.index(f'{current} lineend')
            if self.text.compare(line_start, '==', line_end):
                new_alignment = requested_alignment
                if new_alignment is None:
                    new_alignment = (
                        "left"
                        if self.typing_style.get("alignment") == "center"
                        else "center"
                    )
                return self.setTypingStyleProperty("alignment", new_alignment)

            new_alignment = requested_alignment
            if new_alignment is None:
                new_alignment = (
                    "left"
                    if self.selectionAllHasStyleProperty(
                        line_start,
                        line_end,
                        "alignment",
                        "center",
                    )
                    else "center"
                )
            result = self.applyStylePropertyToRange(
                line_start,
                line_end,
                "alignment",
                new_alignment,
            )
            self.updateToolbarStyleFromSelection()
            self.scheduleCenteredTextLayoutRefresh()
            return result

        self.removeCenteredTextPadding()
        selected_range = self.selectedTextRange(show_error=False)
        if selected_range is None:
            return 'break'

        start, finish = selected_range
        line_ranges = self.selectionLineRanges(start, finish)
        new_alignment = requested_alignment
        if new_alignment is None:
            new_alignment = (
                "left"
                if self.lineRangesAllHaveStyleProperty(line_ranges, "alignment", "center")
                else "center"
            )
        result = 'break'
        for line_start, line_end in line_ranges:
            if self.text.compare(line_start, '<', line_end):
                result = self.applyStylePropertyToRange(
                    line_start,
                    line_end,
                    "alignment",
                    new_alignment,
                )
        self.updateToolbarStyleFromSelection()
        self.scheduleCenteredTextLayoutRefresh()
        return result

    def applySelectedFontFamily(self):
        return self.applyStylePropertyToSelection(
            "font_family",
            self.font_family_var.get() or self.DEFAULT_FONT_FAMILY,
        )

    def applySelectedFontSize(self):
        try:
            font_size = int(self.font_size_var.get())
        except (tk.TclError, ValueError):
            font_size = self.DEFAULT_FONT_SIZE

        font_size = min(96, max(6, font_size))
        self.font_size_var.set(font_size)
        return self.applyStylePropertyToSelection("font_size", font_size)

    def askForFontSize(self):
        font_size = simpledialog.askinteger(
            'Font Size',
            'Size:',
            parent=self.window,
            initialvalue=self.font_size_var.get(),
            minvalue=6,
            maxvalue=96,
        )
        if font_size is None:
            return None

        self.font_size_var.set(font_size)
        return self.applySelectedFontSize()

    def chooseTextColorForSelection(self):
        selected_range = self.selectedTextRange(show_error=False)
        current_color = self.typing_style["color"]
        if selected_range is not None:
            current_color = self.getTextStyleAt(selected_range[0])["color"]

        selected_color = colorchooser.askcolor(
            color=current_color,
            parent=self.window,
            title='Choose text color',
        )
        if selected_color[1] is None:
            return None

        return self.applyStylePropertyToSelection("color", selected_color[1])

    def showInsertTableDialog(self):
        if self.UI_popup is not None:
            self.UI_popup.lift()
            return None

        self.UI_popup = (tableWin := tk.Toplevel(self.window))
        tableWin.title('Insert Table')
        tableWin.geometry('260x165')
        tableWin.resizable(False, False)
        tableWin.wm_protocol('WM_DELETE_WINDOW', self.killUIPopup)

        rows_var = tk.IntVar(value=3)
        columns_var = tk.IntVar(value=3)
        header_var = tk.BooleanVar(value=True)

        tk.Label(tableWin, text='Rows').grid(row=0, column=0, sticky='e', padx=(14, 8), pady=(14, 6))
        rows_spin = tk.Spinbox(tableWin, from_=1, to=50, width=6, textvariable=rows_var)
        rows_spin.grid(row=0, column=1, sticky='w', pady=(14, 6))

        tk.Label(tableWin, text='Columns').grid(row=1, column=0, sticky='e', padx=(14, 8), pady=6)
        columns_spin = tk.Spinbox(tableWin, from_=1, to=20, width=6, textvariable=columns_var)
        columns_spin.grid(row=1, column=1, sticky='w', pady=6)

        header_check = tk.Checkbutton(tableWin, text='Header row', variable=header_var)
        header_check.grid(row=2, column=0, columnspan=2, sticky='w', padx=14, pady=6)

        buttonFrame = tk.Frame(tableWin)
        buttonFrame.grid(row=3, column=0, columnspan=2, sticky='e', padx=14, pady=(8, 12))

        def applyTable():
            try:
                rows = int(rows_var.get())
                columns = int(columns_var.get())
            except (tk.TclError, ValueError):
                messagebox.showerror('Invalid table size', 'Rows and columns must be numbers')
                return None

            self.insertTable(rows, columns, header_var.get())
            self.killUIPopup()
            return None

        tk.Button(buttonFrame, text='Insert', command=applyTable).pack(side='right')
        tk.Button(buttonFrame, text='Cancel', command=self.killUIPopup).pack(side='right', padx=(0, 6))

        rows_spin.bind('<Return>', lambda _: applyTable())
        columns_spin.bind('<Return>', lambda _: applyTable())
        rows_spin.focus_set()
        rows_spin.selection_range(0, 'end')

        return None

    def columnLabel(self, column_index):
        label = ''
        column_index += 1
        while column_index:
            column_index, remainder = divmod(column_index - 1, 26)
            label = chr(ord('A') + remainder) + label
        return label

    def formatTableRow(self, cells):
        return '| ' + '\t| '.join(cells) + '\t|'

    def buildTableText(self, rows, columns, has_header=False):
        rows = min(50, max(1, int(rows)))
        columns = min(20, max(1, int(columns)))
        table_rows = []

        if has_header:
            header_cells = [
                f'Col {self.columnLabel(column_index)}'
                for column_index in range(columns)
            ]
            separator_cells = [
                '-' * max(3, len(cell))
                for cell in header_cells
            ]
            table_rows.append(self.formatTableRow(header_cells))
            table_rows.append(self.formatTableRow(separator_cells))
            rows -= 1

        cell_number = 1
        for _ in range(rows):
            cells = []
            for _ in range(columns):
                cells.append(f'Cell {cell_number}')
                cell_number += 1
            table_rows.append(self.formatTableRow(cells))

        return '\n'.join(table_rows)

    def insertTable(self, rows, columns, has_header=False):
        rows = min(50, max(1, int(rows)))
        columns = min(20, max(1, int(columns)))

        if self.text.tag_ranges('sel'):
            self.text.delete('sel.first', 'sel.last')

        self.insertStyledText('insert', self.buildTableText(rows, columns, has_header), self.typing_style)
        self.refreshTableLayout()
        self.text.see('insert')
        self.updateToolbarStyleFromSelection()
        return 'break'

    def isTableTag(self, tag):
        return tag.startswith(self.TABLE_TAG_PREFIX)

    def removeTableLayoutTags(self):
        for tag in list(self.text.tag_names()):
            if self.isTableTag(tag):
                self.text.tag_remove(tag, '1.0', 'end')

    def lineHasTableCells(self, line_number):
        return '\t' in self.text.get(f'{line_number}.0', f'{line_number}.end')

    def tableRowCells(self, line_number):
        line = self.text.get(f'{line_number}.0', f'{line_number}.end')
        if '\t' not in line:
            return []

        cells = []
        for part in line.split('\t'):
            part = part.strip()
            if part == '|':
                continue
            if part.startswith('|'):
                part = part[1:].strip()
            if part.endswith('|'):
                part = part[:-1].strip()
            cells.append(part)

        return cells

    def isTableSeparatorCells(self, cells):
        return bool(cells) and all(re.fullmatch(r'-+', cell or '') for cell in cells)

    def resizeHeaderSeparatorForTable(self, start_line, finish_line):
        if finish_line - start_line < 1:
            return None

        separator_line = start_line + 1
        separator_cells = self.tableRowCells(separator_line)
        if not self.isTableSeparatorCells(separator_cells):
            return None

        column_count = len(separator_cells)
        column_widths = [3] * column_count
        for line_number in range(start_line, finish_line + 1):
            if line_number == separator_line:
                continue

            cells = self.tableRowCells(line_number)
            for column_index in range(min(column_count, len(cells))):
                column_widths[column_index] = max(
                    column_widths[column_index],
                    len(cells[column_index]),
                )

        resized_separator = self.formatTableRow([
            '-' * width
            for width in column_widths
        ])
        current_separator = self.text.get(f'{separator_line}.0', f'{separator_line}.end')
        if resized_separator == current_separator:
            return None

        self.text.delete(f'{separator_line}.0', f'{separator_line}.end')
        self.text.insert(f'{separator_line}.0', resized_separator)
        return None

    def tableLineCellWidths(self, line_number):
        line_start = f'{line_number}.0'
        line_end = f'{line_number}.end'
        current = line_start
        widths = [0]
        font_cache = {}

        while self.text.compare(current, '<', line_end):
            next_index = self.text.index(f'{current}+1c')
            char = self.text.get(current, next_index)
            if char == '\t':
                widths.append(0)
                current = next_index
                continue

            if self.indexHasAlignmentPadding(current):
                current = next_index
                continue

            style = self.getTextStyleAt(current)
            key = self._style_key(style)
            if key not in font_cache:
                font_cache[key] = self.textStyleFont(style)
            widths[-1] += font_cache[key].measure(char)
            current = next_index

        return widths

    def tableTabStopsForLines(self, start_line, finish_line):
        column_widths = []
        for line_number in range(start_line, finish_line + 1):
            cell_widths = self.tableLineCellWidths(line_number)
            for column_index, cell_width in enumerate(cell_widths):
                if column_index == len(column_widths):
                    column_widths.append(0)
                column_widths[column_index] = max(column_widths[column_index], cell_width)

        stops = []
        position = 0
        for width in column_widths[:-1]:
            position += max(width, self.TABLE_MIN_CELL_WIDTH) + self.TABLE_COLUMN_GAP
            stops.append(position)

        return tuple(stops)

    def refreshTableLayout(self):
        self.cancelScheduledTableLayoutRefresh()
        was_modified = bool(self.text.edit_modified())
        self.removeTableLayoutTags()

        last_line = int(self.text.index('end-1c').split('.')[0])
        line_number = 1
        while line_number <= last_line:
            if not self.lineHasTableCells(line_number):
                line_number += 1
                continue

            block_start = line_number
            while line_number <= last_line and self.lineHasTableCells(line_number):
                line_number += 1
            block_finish = line_number - 1

            self.resizeHeaderSeparatorForTable(block_start, block_finish)
            tag = f'{self.TABLE_TAG_PREFIX}{block_start}'
            tab_stops = self.tableTabStopsForLines(block_start, block_finish)
            self.text.tag_configure(tag, tabs=tab_stops)
            for tagged_line in range(block_start, block_finish + 1):
                self.text.tag_add(tag, f'{tagged_line}.0', f'{tagged_line}.end')

        self.text.edit_modified(was_modified)
        return None

    def scheduleTableLayoutRefresh(self, event=None):
        if self.table_layout_after_id is None:
            self.table_layout_after_id = self.window.after_idle(
                self.runScheduledTableLayoutRefresh
            )
        return None

    def cancelScheduledTableLayoutRefresh(self, event=None):
        if self.table_layout_after_id is not None:
            try:
                self.window.after_cancel(self.table_layout_after_id)
            except tk.TclError:
                pass
            self.table_layout_after_id = None

        return None

    def runScheduledTableLayoutRefresh(self):
        self.table_layout_after_id = None
        return self.refreshTableLayout()
        
    def flattenRTFTokens(self, structure):
        for token in structure:
            if isinstance(token, list):
                yield from self.flattenRTFTokens(token)
            else:
                yield token

    def firstRTFCommand(self, structure):
        for token in structure:
            if isinstance(token, tuple) and token[0] == 'RTFCMD':
                return token[1]
        return None

    def hasDirectRTFCommand(self, structure, command):
        """Check a group itself, without matching commands in child groups."""
        return any(
            isinstance(token, tuple)
            and token == ('RTFCMD', command)
            for token in structure
        )

    def findRTFGroup(self, structure, command):
        for token in structure:
            if isinstance(token, list):
                if self.firstRTFCommand(token) == command:
                    return token
                found = self.findRTFGroup(token, command)
                if found is not None:
                    return found
        return None

    def parseRTFFontTable(self, structure):
        font_group = self.findRTFGroup(structure, 'fonttbl')
        if font_group is None:
            return {0: self.DEFAULT_FONT_FAMILY}

        fonts = {}
        current_font_id = None
        font_name = ''

        for token_type, token_value in self.flattenRTFTokens(font_group):
            if token_type == 'RTFCMD':
                match = re.fullmatch(r'f(\d+)', token_value)
                if match:
                    current_font_id = int(match.group(1))
                    font_name = ''
                continue

            if current_font_id is None or token_type not in {'TEXT', 'CMDPARAM'}:
                continue

            font_name += token_value
            if ';' in font_name:
                name, font_name = font_name.split(';', 1)
                name = name.strip()
                if name:
                    fonts[current_font_id] = name
                current_font_id = None

        if 0 not in fonts:
            fonts[0] = self.DEFAULT_FONT_FAMILY
        return fonts

    def parseRTFColorTable(self, structure):
        color_group = self.findRTFGroup(structure, 'colortbl')
        if color_group is None:
            return {0: self.DEFAULT_TEXT_COLOR}

        entries = []
        current_color = {"red": None, "green": None, "blue": None}
        saw_rgb = False

        for token_type, token_value in self.flattenRTFTokens(color_group):
            if token_type == 'RTFCMD':
                match = re.fullmatch(r'(red|green|blue)(\d+)(;*)', token_value)
                if match:
                    current_color[match.group(1)] = int(match.group(2))
                    saw_rgb = True
                    for _ in range(match.group(3).count(';')):
                        red = current_color["red"] or 0
                        green = current_color["green"] or 0
                        blue = current_color["blue"] or 0
                        entries.append(f"#{red:02x}{green:02x}{blue:02x}")
                        current_color = {"red": None, "green": None, "blue": None}
                        saw_rgb = False
                continue

            if token_type not in {'TEXT', 'CMDPARAM'}:
                continue

            for _ in range(token_value.count(';')):
                if saw_rgb:
                    red = current_color["red"] or 0
                    green = current_color["green"] or 0
                    blue = current_color["blue"] or 0
                    entries.append(f"#{red:02x}{green:02x}{blue:02x}")
                else:
                    entries.append(self.DEFAULT_TEXT_COLOR)
                current_color = {"red": None, "green": None, "blue": None}
                saw_rgb = False

        if not entries:
            entries.append(self.DEFAULT_TEXT_COLOR)
        return dict(enumerate(entries))

    def extractRTFImageHex(self, structure):
        hex_chunks = []
        for token_type, token_value in self.flattenRTFTokens(structure):
            if token_type not in {'TEXT', 'CMDPARAM'}:
                continue

            if token_value.strip() == '':
                continue

            if re.fullmatch(r'[0-9a-fA-F\s]+', token_value):
                hex_chunks.append(token_value)

        return ''.join(hex_chunks)

    def createEmbeddedImage(self, index, pil_image):
        source_image = pil_image.copy()
        tk_image = ImageTk.PhotoImage(source_image)
        self.tkinter_imagelist.append(tk_image)
        embedded_name = self.text.image_create(index, image=tk_image)
        self.embedded_images[embedded_name] = {
            "original": source_image,
            "photo": tk_image,
        }
        return embedded_name

    def createEmbeddedFile(self, index, filename, data):
        """Insert a self-contained attachment widget into the text document."""
        filename = os.path.basename(filename) or 'attachment.bin'
        label = tk.Label(
            self.text.widget,
            text=f'\U0001f4ce {filename}',
            cursor='hand2',
            relief='groove',
            borderwidth=1,
            padx=5,
            pady=2,
        )
        self.text.window_create(index, window=label)
        embedded_name = str(label)
        self.embedded_files[embedded_name] = {
            'filename': filename,
            'data': bytes(data),
            'widget': label,
        }
        label.bind('<Double-1>', lambda _event, name=embedded_name: self.openEmbeddedFile(name))
        label.bind('<Button-3>', lambda event, name=embedded_name: self.showEmbeddedFileMenu(event, name))
        return embedded_name

    def showEmbeddedFileMenu(self, event, embedded_name):
        menu = tk.Menu(self.window, tearoff=False)
        menu.add_command(label='Copy attachment', command=lambda: self.copyEmbeddedFile(embedded_name))
        menu.add_command(label='Open attachment', command=lambda: self.openEmbeddedFile(embedded_name))
        menu.add_separator()
        menu.add_command(
            label='Calculate SHA-1 hash',
            command=lambda: self.calculateEmbeddedFileSha1(embedded_name),
        )
        menu.tk_popup(event.x_root, event.y_root)
        return 'break'

    def calculateEmbeddedFileSha1(self, embedded_name):
        """Calculate and display the SHA-1 digest of an embedded attachment."""
        attachment = self.embedded_files.get(embedded_name)
        if attachment is None:
            return None

        digest = hashlib.sha1(attachment['data']).hexdigest()
        self.showSha1HashDialog(attachment['filename'], digest)
        return digest

    def showSha1HashDialog(self, filename, digest):
        """Show a selectable SHA-1 digest with an explicit copy action."""
        dialog = tk.Toplevel(self.window)
        dialog.title('SHA-1 hash')
        dialog.transient(self.window)
        dialog.resizable(False, False)

        content = ttk.Frame(dialog, padding=12)
        content.grid(row=0, column=0, sticky='nsew')
        ttk.Label(content, text=filename).grid(
            row=0,
            column=0,
            columnspan=2,
            sticky='w',
            pady=(0, 8),
        )

        digest_entry = ttk.Entry(content, width=42)
        digest_entry.insert(0, digest)
        digest_entry.configure(state='readonly')
        digest_entry.grid(row=1, column=0, columnspan=2, sticky='ew')

        copy_button = ttk.Button(content, text='Copy')

        def copy_digest():
            self.copySha1Hash(digest)
            copy_button.configure(text='Copied!')

        copy_button.configure(command=copy_digest)
        copy_button.grid(row=2, column=0, sticky='e', padx=(0, 6), pady=(10, 0))
        ttk.Button(content, text='Close', command=dialog.destroy).grid(
            row=2,
            column=1,
            sticky='w',
            pady=(10, 0),
        )

        digest_entry.focus_set()
        digest_entry.selection_range(0, 'end')
        dialog.bind('<Escape>', lambda _event: dialog.destroy())
        return dialog

    def copySha1Hash(self, digest):
        """Copy a SHA-1 digest as plain text."""
        self.window.clipboard_clear()
        self.window.clipboard_append(digest)
        return 'break'

    def materializeEmbeddedFile(self, embedded_name):
        attachment = self.embedded_files.get(embedded_name)
        if attachment is None:
            return None
        folder = tempfile.mkdtemp(dir=self.attachment_tempdir.name)
        path = os.path.join(folder, attachment['filename'])
        with open(path, 'wb') as output:
            output.write(attachment['data'])
        return path

    def fileDropClipboardBytes(self, paths):
        # DROPFILES followed by a double-NUL-terminated UTF-16 path list.
        names = ('\0'.join(os.path.abspath(path) for path in paths) + '\0\0').encode('utf-16-le')
        return struct.pack('<IiiII', 20, 0, 0, 0, 1) + names

    def copyEmbeddedFile(self, embedded_name):
        path = self.materializeEmbeddedFile(embedded_name)
        if path is None:
            return None
        self.clip.open_clipboard()
        try:
            self.clip.clear_clipboard()
            self.clip.set_clipboard(self.fileDropClipboardBytes([path]), self.clip.FILES)
            preferred_drop_effect = self.clip.register_format('Preferred DropEffect')
            if preferred_drop_effect is not None:
                # DROPEFFECT_COPY: the temporary source must never be moved/deleted.
                self.clip.set_clipboard(struct.pack('<I', 1), preferred_drop_effect)
            filename_w = self.clip.register_format('FileNameW')
            if filename_w is not None:
                # The clipboard helper appends one byte; include the other half
                # of the UTF-16 NUL terminator in this payload.
                self.clip.set_clipboard(path.encode('utf-16-le') + b'\0', filename_w)
        finally:
            self.clip.close_clipboard()
        return 'break'

    def openEmbeddedFile(self, embedded_name):
        path = self.materializeEmbeddedFile(embedded_name)
        if path is None:
            return None
        try:
            os.startfile(path)
        except (AttributeError, OSError) as exc:
            messagebox.showerror('Could not open attachment', str(exc))
        return 'break'

    def findTkImageByName(self, image_name):
        for tk_image in self.tkinter_imagelist:
            if str(tk_image) == image_name:
                return tk_image
        return None

    def getPhotoImageForEmbeddedImage(self, embedded_name):
        image_data = self.embedded_images.get(embedded_name)
        if image_data is not None:
            return image_data["photo"]

        try:
            current_image_name = self.text.image_cget(embedded_name, 'image')
        except tk.TclError:
            current_image_name = embedded_name

        return self.findTkImageByName(current_image_name)

    def resizeEmbeddedImage(self, embedded_name, width, height):
        width = max(self.IMAGE_RESIZE_MIN_SIZE, int(round(width)))
        height = max(self.IMAGE_RESIZE_MIN_SIZE, int(round(height)))

        image_data = self.embedded_images.get(embedded_name)
        if image_data is None:
            current_photo = self.getPhotoImageForEmbeddedImage(embedded_name)
            if current_photo is None:
                return None

            image_data = {
                "original": ImageTk.getimage(current_photo).copy(),
                "photo": current_photo,
            }
            self.embedded_images[embedded_name] = image_data

        original_image = image_data["original"]
        resampling_filter = getattr(
            getattr(Image, "Resampling", Image),
            "LANCZOS",
            Image.BICUBIC,
        )
        resized_image = original_image.resize((width, height), resampling_filter)
        resized_photo = ImageTk.PhotoImage(resized_image)
        old_photo = image_data["photo"]

        self.text.image_configure(embedded_name, image=resized_photo)
        image_data["photo"] = resized_photo
        self.tkinter_imagelist.append(resized_photo)
        if old_photo in self.tkinter_imagelist:
            self.tkinter_imagelist.remove(old_photo)

        self.markCurrentDocumentModified()
        return resized_photo

    def imageResizeHandleAtPoint(self, x, y, bbox):
        bbox_x, bbox_y, bbox_width, bbox_height = bbox
        handle_size = self.IMAGE_RESIZE_HANDLE_SIZE
        near_left = abs(x - bbox_x) <= handle_size
        near_right = abs(x - (bbox_x + bbox_width)) <= handle_size
        near_top = abs(y - bbox_y) <= handle_size
        near_bottom = abs(y - (bbox_y + bbox_height)) <= handle_size

        if not (near_left or near_right or near_top or near_bottom):
            return None

        if near_left and near_top:
            return 'nw'
        if near_right and near_top:
            return 'ne'
        if near_left and near_bottom:
            return 'sw'
        if near_right and near_bottom:
            return 'se'
        if near_left:
            return 'w'
        if near_right:
            return 'e'
        if near_top:
            return 'n'
        if near_bottom:
            return 's'

        return None

    def imageResizeHitAtPoint(self, x, y):
        for token_type, token_value, token_index in self.text.dump('1.0', 'end'):
            if token_type != 'image':
                continue

            bbox = self.text.bbox(token_index)
            if bbox is None:
                continue

            bbox_x, bbox_y, bbox_width, bbox_height = bbox
            handle_size = self.IMAGE_RESIZE_HANDLE_SIZE
            if not (
                bbox_x - handle_size <= x <= bbox_x + bbox_width + handle_size
                and bbox_y - handle_size <= y <= bbox_y + bbox_height + handle_size
            ):
                continue

            handle = self.imageResizeHandleAtPoint(x, y, bbox)
            if handle is None:
                continue

            return {
                "name": token_value,
                "index": token_index,
                "bbox": bbox,
                "handle": handle,
            }

        return None

    def imageResizeCursor(self, handle):
        if handle in {'e', 'w'}:
            return 'sb_h_double_arrow'
        if handle in {'n', 's'}:
            return 'sb_v_double_arrow'
        if handle in {'nw', 'se'}:
            return 'size_nw_se'
        if handle in {'ne', 'sw'}:
            return 'size_ne_sw'
        return ''

    def configureTextCursor(self, cursor):
        cursor = cursor or self.TEXT_CURSOR
        if cursor == self.current_text_cursor:
            return None

        try:
            self.text.configure(cursor=cursor)
        except tk.TclError:
            self.text.configure(cursor='fleur')

        self.current_text_cursor = cursor

    def updateImageResizeCursor(self, event):
        if self.image_resize_state is not None:
            return None

        hit = self.imageResizeHitAtPoint(event.x, event.y)
        self.configureTextCursor(self.imageResizeCursor(hit["handle"]) if hit else self.TEXT_CURSOR)
        return None

    def beginImageResize(self, event):
        hit = self.imageResizeHitAtPoint(event.x, event.y)
        if hit is None:
            self.image_resize_state = None
            return None

        photo_image = self.getPhotoImageForEmbeddedImage(hit["name"])
        if photo_image is None:
            return None

        pil_image = ImageTk.getimage(photo_image)
        width, height = pil_image.size
        self.image_resize_state = {
            "name": hit["name"],
            "index": hit["index"],
            "handle": hit["handle"],
            "start_x": event.x,
            "start_y": event.y,
            "start_width": width,
            "start_height": height,
        }
        self.text.mark_set('insert', hit["index"])
        return 'break'

    def calculateImageResizeSize(self, resize_state, current_x, current_y, preserve_aspect):
        handle = resize_state["handle"]
        width = resize_state["start_width"]
        height = resize_state["start_height"]
        dx = current_x - resize_state["start_x"]
        dy = current_y - resize_state["start_y"]

        if 'e' in handle:
            width += dx
        elif 'w' in handle:
            width -= dx

        if 's' in handle:
            height += dy
        elif 'n' in handle:
            height -= dy

        width = max(self.IMAGE_RESIZE_MIN_SIZE, width)
        height = max(self.IMAGE_RESIZE_MIN_SIZE, height)

        if preserve_aspect:
            aspect_ratio = resize_state["start_width"] / resize_state["start_height"]
            resizes_width = 'e' in handle or 'w' in handle
            resizes_height = 'n' in handle or 's' in handle

            if resizes_width and not resizes_height:
                height = width / aspect_ratio
            elif resizes_height and not resizes_width:
                width = height * aspect_ratio
            else:
                width_scale = width / resize_state["start_width"]
                height_scale = height / resize_state["start_height"]
                if abs(width_scale - 1) >= abs(height_scale - 1):
                    height = width / aspect_ratio
                else:
                    width = height * aspect_ratio

        return (
            max(self.IMAGE_RESIZE_MIN_SIZE, int(round(width))),
            max(self.IMAGE_RESIZE_MIN_SIZE, int(round(height))),
        )

    def dragImageResize(self, event):
        if self.image_resize_state is None:
            return None

        width, height = self.calculateImageResizeSize(
            self.image_resize_state,
            event.x,
            event.y,
            bool(event.state & 0x0001),
        )
        self.resizeEmbeddedImage(self.image_resize_state["name"], width, height)
        return 'break'

    def finishImageResize(self, event):
        if self.image_resize_state is None:
            return None

        self.image_resize_state = None
        self.updateImageResizeCursor(event)
        return 'break'

    def displayRTFImageGroup(self, structure, insertion_index='end'):
        img_buildout_hex = self.extractRTFImageHex(structure)

        if img_buildout_hex == '':
            return None

        try:
            imgdata = io.BytesIO(bytes.fromhex(img_buildout_hex.replace('\r', '').replace('\n', '').replace(' ', '')))
            img = Image.open(imgdata)
        except (OSError, ValueError) as exc:
            print(f'ERROR: Could not load embedded image: {exc}')
            return None

        self.createEmbeddedImage(insertion_index, img)

        return None

    def applyRTFCommandToStyle(self, command, style, insertion_index='end'):
        if command == 'par':
            self.insertStyledText(insertion_index, '\n', style)
            return style

        if command == 'tab':
            self.insertStyledText(insertion_index, '\t', style)
            return style

        if command == 'pard':
            style["alignment"] = "left"
            return style

        if command == 'plain':
            return self.defaultTextStyle()

        if command == 'qc':
            style["alignment"] = "center"
            return style

        if command == 'ql':
            style["alignment"] = "left"
            return style

        bold_match = re.fullmatch(r'b(0?)', command)
        if bold_match:
            style["bold"] = bold_match.group(1) != "0"
            return style

        italic_match = re.fullmatch(r'i(0?)', command)
        if italic_match:
            style["italic"] = italic_match.group(1) != "0"
            return style

        color_match = re.fullmatch(r'cf(\d+)', command)
        if color_match:
            style["color"] = self.color_table.get(
                int(color_match.group(1)),
                self.DEFAULT_TEXT_COLOR,
            )
            return style

        font_match = re.fullmatch(r'f(\d+)', command)
        if font_match:
            style["font_family"] = self.font_table.get(
                int(font_match.group(1)),
                self.DEFAULT_FONT_FAMILY,
            )
            return style

        size_match = re.fullmatch(r'fs(\d+)', command)
        if size_match:
            style["font_size"] = max(1, round(int(size_match.group(1)) / 2))
            return style

        return style

    def displayNestedRTFStructure(self, structure, insertion_index='end'):
        self.font_table = self.parseRTFFontTable(structure)
        self.color_table = self.parseRTFColorTable(structure)
        self._displayNestedRTFStructure(
            structure,
            self.defaultTextStyle(),
            insertion_index,
        )

    def _displayNestedRTFStructure(self, structure, style, insertion_index='end'):
        first_command = self.firstRTFCommand(structure)
        if first_command in {'fonttbl', 'colortbl'}:
            return None

        if first_command == 'pict':
            return self.displayRTFImageGroup(structure, insertion_index)

        if self.hasDirectRTFCommand(structure, 'supertextfile'):
            return self.displayRTFFileGroup(structure, insertion_index)

        current_style = style.copy()
        for token in structure:
            if isinstance(token, list):
                self._displayNestedRTFStructure(
                    token,
                    current_style.copy(),
                    insertion_index,
                )
                continue

            token_type, token_value = token
            if token_type in {'TEXT', 'CMDPARAM'}:
                self.insertStyledText(insertion_index, token_value, current_style)
            elif token_type == 'RTFCMD':
                current_style = self.applyRTFCommandToStyle(
                    token_value,
                    current_style,
                    insertion_index,
                )
            else:
                print('ERROR: UNKNOWN PARSE TOKEN TO DISPLAY')
                print(token)

        return None

    def customRTFGroupValue(self, structure, command):
        group = self.findRTFGroup(structure, command)
        if group is None:
            return ''
        return ''.join(
            value for kind, value in self.flattenRTFTokens(group)
            if kind in {'TEXT', 'CMDPARAM'} and value.strip()
        )

    def displayRTFFileGroup(self, structure, insertion_index='end'):
        try:
            filename = bytes.fromhex(self.customRTFGroupValue(structure, 'supertextfilename')).decode('utf-8')
            data = bytes.fromhex(self.customRTFGroupValue(structure, 'supertextdata'))
        except (ValueError, UnicodeDecodeError) as exc:
            print(f'Could not decode embedded file: {exc}')
            return None
        return self.createEmbeddedFile(insertion_index, filename, data)

    def confirmDocumentReplacement(self, document):
        self.captureActiveDocumentState()
        if not document.dirty:
            return True

        answer = messagebox.askyesnocancel(
            'Save changes?',
            f'Save changes to {self.documentTabTitle(document).lstrip("* ")} before viewing another note?',
        )
        if answer is None:
            if document.relative_path:
                self.selectNodePath(document.relative_path, open_document=False)
            return False
        if answer:
            self.activateDocument(document)
            return self.writeCurrentDocument(show_confirmation=False)
        return True

    def tryReadShowRTF(
        self,
        event,
        open_in_new_tab=True,
        force_new_tab=False,
        reuse_open_tab=True,
    ): # event is not used
        selection = self.selected_node = self.tree.selection()[0] if len(self.tree.selection()) != 0 else ()
        
        if len(selection) == 0: # if nothing is selected
            return None

        sel_path = self.get_node_path(selection)
        
        if sel_path == '':
            return None
        
        node_path = self.resolveNodePath(sel_path) + '.rtf'
        normalized_path = self.normalizedDocumentPath(node_path)
        active_document_matches = (
            self.active_document is not None
            and self.normalizedDocumentPath(self.active_document.path) == normalized_path
        )
        if active_document_matches and not force_new_tab:
            return self.active_document

        open_document = self.open_documents_by_path.get(normalized_path)
        if open_document is not None and reuse_open_tab and not force_new_tab:
            self.selectDocumentTab(open_document)
            return open_document

        cloned_modified_document = False
        active_document_matches = (
            force_new_tab
            and self.active_document is not None
            and self.normalizedDocumentPath(self.active_document.path) == normalized_path
        )
        if active_document_matches:
            self.captureActiveDocumentState()
            data = self.convertToRTF('1.0', 'end')
            cloned_modified_document = self.active_document.dirty
        else:
            try:
                with open(node_path, 'r', encoding='utf-8') as fi:
                    data = fi.read()
            except UnicodeDecodeError:
                with open(node_path, 'r') as fi:
                    data = fi.read()
            except OSError as exc:
                messagebox.showerror('Error Reading Node', f'Could not read node file: {exc}')
                return None

        # parse the RTF using the RTF parser
        try:
            rt = RTFParser(data).parseme()
        except RTFParseError as exc:
            messagebox.showerror('Error Reading Node', f'Could not parse node RTF: {exc}')
            return None

        # verify the header matches the expected for an RTF that this program can read
        if not self.isSupportedRTF(rt):
            messagebox.showerror('Error Reading Node', 'Unsupported RTF header')
            return None

        document = self.active_document
        can_reuse_placeholder = (
            document is not None
            and not document.path
            and self.text.get('1.0', 'end-1c') == ''
        )
        if open_in_new_tab and not can_reuse_placeholder:
            document = self.createDocumentTab(node_path, sel_path)
        else:
            if document is None:
                document = self.createDocumentTab()
            elif document.path and not self.confirmDocumentReplacement(document):
                return None

            if document.path:
                self.unregisterOpenDocumentPath(document)
            document.path = node_path
            document.relative_path = sel_path
            self.registerOpenDocumentPath(document)

        document.loading = True
        document.tkinter_imagelist = []
        document.embedded_images = {}
        document.embedded_files = {}
        document.font_table = {0: self.DEFAULT_FONT_FAMILY}
        document.color_table = {0: self.DEFAULT_TEXT_COLOR}
        document.style_tags = {}
        document.style_tag_names = {}
        document.style_tag_counter = 0
        document.typing_style = self.defaultTextStyle()
        document.current_text_cursor = self.TEXT_CURSOR
        document.image_resize_state = None
        self.activateDocument(document)

        try:
            self.text.delete('1.0', 'end')
            self.text.edit_reset()
            self.displayNestedRTFStructure(rt)
            # A loaded note starts with a clean undo and modified-state baseline.
            self.text.edit_reset()
            self.text.edit_modified(False)
            document.dirty = False
            self.captureActiveDocumentState()
            self.updateDocumentTabTitle(document)
        finally:
            document.loading = False

        if cloned_modified_document:
            self.text.edit_modified(True)
            document.dirty = True
            self.captureActiveDocumentState()
            self.updateDocumentTabTitle(document)

        return document

    def isSupportedRTF(self, rt):
        if len(rt) < 3:
            return False

        if rt[0] != ('RTFCMD', 'rtf1') or rt[1] != ('RTFCMD', 'ansi'):
            return False

        has_paragraph_defaults = any(
            token == ('RTFCMD', 'pard')
            for token in rt
            if isinstance(token, tuple)
        )
        has_font_table = self.findRTFGroup(rt, 'fonttbl') is not None

        return has_paragraph_defaults and has_font_table

    def escapeRTFText(self, txt):
        txt = txt.replace('\\', '\\\\').replace('{', r'\{').replace('}', r'\}')
        txt = txt.replace('\t', r'{\tab }')
        txt = txt.replace('\n', r'{\par }')
        return ''.join([fr"\u{ord(c)}?" if ord(c) > 0x7F else c for c in txt])

    def escapeRTFFontName(self, font_name):
        return self.escapeRTFText(font_name).replace(';', '').strip() or self.DEFAULT_FONT_FAMILY

    def assignRTFFontId(self, font_ids, font_family):
        font_family = font_family or self.DEFAULT_FONT_FAMILY
        if font_family not in font_ids:
            font_ids[font_family] = len(font_ids)
        return font_ids[font_family]

    def assignRTFColorId(self, color_ids, color):
        color = self.normalizeColor(color)
        if color is None:
            return 0
        if color not in color_ids:
            color_ids[color] = len(color_ids) + 1
        return color_ids[color]

    def buildRTFHeader(self, font_ids, color_ids):
        fonts_by_id = sorted(font_ids.items(), key=lambda item: item[1])
        font_table = ''.join(
            rf'{{\f{font_id}\fswiss {self.escapeRTFFontName(font_family)};}}'
            for font_family, font_id in fonts_by_id
        )

        header = r'{\rtf1\ansi\deff0' + r'{\fonttbl' + font_table + '}'

        if color_ids:
            colors_by_id = sorted(color_ids.items(), key=lambda item: item[1])
            color_table = ';'
            for color, _ in colors_by_id:
                red = int(color[1:3], 16)
                green = int(color[3:5], 16)
                blue = int(color[5:7], 16)
                color_table += rf'\red{red}\green{green}\blue{blue};'
            header += r'{\colortbl ' + color_table + '}'

        header += rf'\pard\f0\fs{self.DEFAULT_FONT_SIZE * 2} '
        return header

    def styleRTFCommandPrefix(self, style, font_ids, color_ids):
        commands = []
        style = {**self.defaultTextStyle(), **style}

        font_id = self.assignRTFFontId(font_ids, style["font_family"])
        if font_id != 0:
            commands.append(rf'\f{font_id}')

        font_size = int(style["font_size"])
        if font_size != self.DEFAULT_FONT_SIZE:
            commands.append(rf'\fs{font_size * 2}')

        color_id = self.assignRTFColorId(color_ids, style["color"])
        if color_id != 0:
            commands.append(rf'\cf{color_id}')

        if style["bold"]:
            commands.append(r'\b')

        if style["italic"]:
            commands.append(r'\i')

        if style["alignment"] == "center":
            commands.append(r'\qc')

        return ''.join(commands)

    def currentDumpStyle(self, active_style_tags):
        style = self.defaultTextStyle()
        for tag in active_style_tags:
            if tag in self.style_tags:
                style.update(self.style_tags[tag])
        return style

    def convertDumpToRTFBody(self, textContents, initial_style_tags=None):
        body = ''
        font_ids = {self.DEFAULT_FONT_FAMILY: 0}
        color_ids = {}
        active_style_tags = list(initial_style_tags or [])
        active_padding_tags = []
        has_formatting = False

        for token_type, token_value, _ in textContents:
            if token_type == 'tagon' and self.isAlignmentPaddingTag(token_value):
                active_padding_tags.append(token_value)
                continue

            if token_type == 'tagoff' and token_value in active_padding_tags:
                active_padding_tags.remove(token_value)
                continue

            if token_type == 'tagon' and token_value in self.style_tags:
                active_style_tags.append(token_value)
                continue

            if token_type == 'tagoff' and token_value in active_style_tags:
                active_style_tags.remove(token_value)
                continue

            if token_type == 'image':
                real_image = self.getPhotoImageForEmbeddedImage(token_value)

                if real_image is None:
                    continue

                ibytes = io.BytesIO()
                shifted_img = ImageTk.getimage(real_image)
                imgx, imgy = shifted_img.size
                shifted_img.save(ibytes, 'PNG')
                body += r'{\pict\pngblip' + rf'\picw{int(imgx*self.rtf_img_factor)}\pich{int(imgy*self.rtf_img_factor)} ' + ibytes.getvalue().hex() + '}'
                continue

            if token_type == 'window' and token_value in self.embedded_files:
                attachment = self.embedded_files[token_value]
                filename_hex = attachment['filename'].encode('utf-8').hex()
                data_hex = attachment['data'].hex()
                body += (r'{\*\supertextfile '
                         r'{\supertextfilename ' + filename_hex + '}'
                         r'{\supertextdata ' + data_hex + '}}')
                continue

            if token_type != 'text':
                continue

            if active_padding_tags:
                continue

            text = self.escapeRTFText(token_value)
            style = self.currentDumpStyle(active_style_tags)
            style_prefix = self.styleRTFCommandPrefix(style, font_ids, color_ids)
            if style_prefix:
                has_formatting = True
                body += '{' + style_prefix + ' ' + text + '}'
            else:
                body += text

        return body, font_ids, color_ids, has_formatting

    def rangeHasFormatting(self, start, finish):
        if any(tag in self.style_tags for tag in self.text.tag_names(start)):
            return True

        return any(
            self.text.tag_nextrange(tag, start, finish)
            for tag in self.style_tags
        )

    def dumpTextWithoutAlignmentPadding(self, dumped_text):
        active_padding_tags = []
        text_parts = []
        for token_type, token_value, _ in dumped_text:
            if token_type == 'tagon' and self.isAlignmentPaddingTag(token_value):
                active_padding_tags.append(token_value)
                continue

            if token_type == 'tagoff' and token_value in active_padding_tags:
                active_padding_tags.remove(token_value)
                continue

            if token_type == 'text' and not active_padding_tags:
                text_parts.append(token_value)

        return text_parts

    def expandTabbedLinesForPlainText(self, lines):
        split_lines = [line.split('\t') for line in lines]
        column_widths = []
        for parts in split_lines:
            for column_index, part in enumerate(parts[:-1]):
                if column_index == len(column_widths):
                    column_widths.append(0)
                column_widths[column_index] = max(column_widths[column_index], len(part))

        expanded_lines = []
        for parts in split_lines:
            if len(parts) == 1:
                expanded_lines.append(parts[0])
                continue

            expanded = ''
            for column_index, part in enumerate(parts[:-1]):
                expanded += part
                expanded += ' ' * (column_widths[column_index] - len(part) + 1)
            expanded += parts[-1]
            expanded_lines.append(expanded)

        return expanded_lines

    def expandTabsForPlainText(self, text):
        lines = text.split('\n')
        expanded_lines = []
        tabbed_block = []

        def flushTabbedBlock():
            if not tabbed_block:
                return None
            expanded_lines.extend(self.expandTabbedLinesForPlainText(tabbed_block))
            tabbed_block.clear()
            return None

        for line in lines:
            if '\t' in line:
                tabbed_block.append(line)
                continue

            flushTabbedBlock()
            expanded_lines.append(line)

        flushTabbedBlock()
        return '\n'.join(expanded_lines)

    def plainTextForClipboard(self, text_parts):
        return self.expandTabsForPlainText(''.join(text_parts))

    def setClipboardPlainText(self, text):
        self.clip.set_clipboard(text.encode('utf-16-le'), self.clip.UNITEXT)
        try:
            self.clip.set_clipboard(text.encode('ansi'), self.clip.TEXT)
        except UnicodeEncodeError:
            pass
    
    # convert a text selection to RTF
    # start to finish of selection
    def convertToRTF(self, start, finish):
        # get the text contents including images
        # tkinter proves "dump" for this
        if finish == 'end':
            finish = 'end-1c'
        initial_style_tags = [
            tag for tag in self.text.tag_names(start)
            if tag in self.style_tags
        ]
        textContents = self.text.dump(start, finish)

        body, font_ids, color_ids, has_formatting = self.convertDumpToRTFBody(
            textContents,
            initial_style_tags,
        )

        if has_formatting or color_ids or len(font_ids) > 1:
            data = self.buildRTFHeader(font_ids, color_ids) + body
        else:
            data = self.RTF_HEADER + body

        data = data.strip() # this is cleaner to remove extra whitespace
        data += '}'
        
        return data
    
    # save an RTF file that is open
    def writeCurrentDocument(self, show_confirmation=True):
        if self.openFile == '':
            messagebox.showerror(title='No open files to save', message='No open files to save')
            return False

        data = self.convertToRTF('1.0', 'end')
        try:
            with open(self.openFile, 'w', encoding='utf-8') as fi:
                fi.write(data)
            self.search_index.update_file(self.openFile)
        except OSError as exc:
            messagebox.showerror('Error Saving Note', f'Could not save note: {exc}')
            return False

        if self.active_document is not None:
            self.active_document.path = self.openFile
            self.active_document.dirty = False
            self.text.edit_modified(False)
            self.captureActiveDocumentState()
            self.updateDocumentTabTitle(self.active_document)
        if show_confirmation:
            messagebox.showinfo(title='Saved file', message='Saved file')
        return True

    def saveRTF(self):
        return self.writeCurrentDocument(show_confirmation=True)

    def saveAllTabs(self, event=None):
        original_document = self.active_document
        self.captureActiveDocumentState()
        saved_count = 0
        for document in list(self.open_documents_by_tab.values()):
            if not document.path:
                continue
            document.dirty = bool(document.text.edit_modified())
            self.activateDocument(document)
            if document.dirty:
                if not self.writeCurrentDocument(show_confirmation=False):
                    if original_document is not None:
                        self.activateDocument(original_document)
                    return 'break'
                saved_count += 1
        if original_document is not None:
            self.activateDocument(original_document)
        if saved_count:
            messagebox.showinfo('Saved files', f'Saved {saved_count} open note(s).')
        return 'break'
    
    def createNewNode(self):
        sel = self.selected_node
        
        if len(sel) == 0:
            sel = ()

        newNodeName = f'newNode{len(self.tree.get_children(sel))}'
        
        path = self.resolveNodePath(os.path.join(self.get_node_path(sel), newNodeName))
        file_path = path + '.rtf'
        
        # create the new dir to go with the new file
        os.makedirs(path, exist_ok=True)
        # create new RTF with basics, just the header
        with open(file_path, 'w') as fi:
            fi.write(self.RTF_HEADER + '}')
        
        self.tree.insert(sel, 'end', text=newNodeName, value='', iid=self.getNextTkinterItemId())

    def documentIsUnderNodePath(self, document_path, node_path):
        document_path = self.normalizedDocumentPath(document_path)
        node_path = self.normalizedDocumentPath(node_path)
        if document_path == self.normalizedDocumentPath(node_path + '.rtf'):
            return True
        try:
            return os.path.commonpath([node_path, document_path]) == node_path
        except ValueError:
            return False

    def closeDocumentsUnderNodePath(self, node_path, force=True):
        for tab_id, document in list(self.open_documents_by_tab.items()):
            if document.path and self.documentIsUnderNodePath(document.path, node_path):
                if not self.closeDocumentTab(
                    tab_id,
                    force=force,
                    create_placeholder=False,
                ):
                    return False
        if not self.editor_tabs.tabs():
            self.activateDocument(self.createDocumentTab())
        return True

    def remapOpenDocumentPaths(self, old_node_path, new_node_path):
        old_node_path = os.path.abspath(os.path.normpath(old_node_path))
        new_node_path = os.path.abspath(os.path.normpath(new_node_path))
        normalized_old_node_path = self.normalizedDocumentPath(old_node_path)
        old_note_path = self.normalizedDocumentPath(old_node_path + '.rtf')

        for document in list(self.open_documents_by_tab.values()):
            if not document.path:
                continue
            normalized_path = self.normalizedDocumentPath(document.path)
            if normalized_path == old_note_path:
                new_document_path = new_node_path + '.rtf'
            else:
                try:
                    is_descendant = (
                        os.path.commonpath([normalized_old_node_path, normalized_path])
                        == normalized_old_node_path
                    )
                except ValueError:
                    is_descendant = False
                if not is_descendant:
                    continue
                new_document_path = os.path.join(
                    new_node_path,
                    os.path.relpath(document.path, old_node_path),
                )

            self.unregisterOpenDocumentPath(document)
            document.path = os.path.normpath(new_document_path)
            relative_file = os.path.relpath(document.path, self._node_root_path())
            document.relative_path = os.path.splitext(relative_file)[0]
            self.registerOpenDocumentPath(document)
            self.updateDocumentTabTitle(document)
            if document is self.active_document:
                self.openFile = document.path
    
    def archiveSelectedNode(self):
        node = self.selected_node
        if not node:
            return None

        relative_path = self.get_node_path(node)
        node_path = self.resolveNodePath(relative_path)
        if not messagebox.askyesno(
            'Archive notes?',
            f'Compress "{relative_path}" and all of its child notes into the archive?',
        ):
            return None

        # Closing affected tabs gives each unsaved document its normal
        # save/discard/cancel prompt before any on-disk files are moved.
        if not self.closeDocumentsUnderNodePath(node_path, force=False):
            return None
        try:
            record = self.archive_store.archive(relative_path)
        except (ArchiveError, OSError, shutil.Error) as exc:
            messagebox.showerror('Archive failed', str(exc))
            return None

        self.populateNodeTree()
        messagebox.showinfo(
            'Notes archived',
            (
                f'Archived "{record.original_path}" and '
                f'{record.note_count} note(s) to the compressed archive.'
            ),
        )
        return 'break'

    def deleteNode(self):
        parent = self.selected_node
        if len(parent) == 0:
            return None

        path = self.resolveNodePath(self.get_node_path(parent))
        result = tk.messagebox.askquestion('Delete', f'Are you sure you want to delete {self.tree.item(parent)["text"]}?')
        
        if result == 'yes':
            children_of_child = self.get_all_children(parent)
            for c in children_of_child:
                self.item_ids.remove(int(c.split('_')[1]))
            self.item_ids.remove(int(parent.split('_')[1]))
            self.tree.delete(*self.tree.get_children(parent))
            self.tree.delete(parent)
            
            shutil.rmtree(path)
            os.remove(path + '.rtf')
            self.closeDocumentsUnderNodePath(path)
        else:
            pass
    
    def renameFileAndDir(self, node, old_path, new_path):
        try:
            old_path_withnodedir = self.resolveNodePath(old_path)
            new_path_withnodedir = self.resolveNodePath(new_path)
            newpath = RenamePathToPath(old_path_withnodedir, new_path_withnodedir)
            if os.path.exists(newpath) or os.path.exists(newpath + '.rtf'):
                raise ValueError('A node with that name already exists')
        except (AssertionError, ValueError) as e:
            messagebox.showerror('Error Renaming Node', str(e) or 'Error Renaming Node')
            return None

        shutil.move(old_path_withnodedir, newpath)
        shutil.move(old_path_withnodedir + '.rtf', newpath + '.rtf')
        self.remapOpenDocumentPaths(old_path_withnodedir, newpath)
        
        old_parent_path = os.path.dirname(os.path.normpath(old_path))
        relative_newpath = os.path.relpath(newpath, self._node_root_path())
        new_parent_path = os.path.dirname(relative_newpath)

        def refresh_parent(parent_path):
            parent_node = self.find_self(parent_path) if parent_path else ''
            parent_fullpath = self.resolveNodePath(parent_path) if parent_path else self._node_root_path()
            self.populateNodeTree(parent_fullpath, parent_node)

        refresh_parent(old_parent_path)
        if old_parent_path != new_parent_path:
            refresh_parent(new_parent_path)

        node = self.find_self(relative_newpath)
        self.tree.selection_set(node)
        self.tree.focus(item=node)
        self.selected_node = node
        node_pointer = node
        while (node_pointer := self.get_node_parent(node_pointer)) != '':
            self.tree.item(node_pointer, open=True)

    def beginMoveNode(self):
        """Wait for the user to click the node that will become the new parent."""
        node = self.selected_node
        if not node:
            return None
        self.cancelInlineRename()
        self.move_source_node = node
        self.tree.widget.configure(cursor='crosshair')
        return 'break'

    def cancelMoveNode(self):
        if self.move_source_node is None:
            return None
        self.move_source_node = None
        self.tree.widget.configure(cursor='')
        return 'break'

    def cancelNodeInteraction(self, event=None):
        if self.move_source_node is not None:
            return self.cancelMoveNode()
        if self.rename_entry is not None:
            self.cancelInlineRename()
            return 'break'
        return None

    def completeMoveNode(self, event):
        source = self.move_source_node
        if source is None:
            return None
        self.ignore_next_tree_release = True

        destination = self.tree.identify('item', event.x, event.y)
        if not destination:
            return 'break'

        pointer = destination
        while pointer:
            if pointer == source:
                messagebox.showerror('Error Moving Node', 'A node cannot be moved inside itself.')
                return 'break'
            pointer = self.get_node_parent(pointer)

        old_path = self.get_node_path(source)
        new_path = os.path.join(
            self.get_node_path(destination),
            self.tree.item(source)['text'],
        )
        self.cancelMoveNode()
        if os.path.normcase(os.path.normpath(new_path)) == os.path.normcase(os.path.normpath(old_path)):
            return 'break'
        self.renameFileAndDir(source, old_path, new_path)
        return 'break'
    
    def killUIPopup(self):
        self.UI_popup.destroy()
        self.UI_popup = None
    
    def cancelInlineRename(self):
        if self.rename_entry is not None:
            self.rename_entry.destroy()
            self.rename_entry = None

    def finishInlineRename(self, node, old_path):
        if self.rename_entry is None:
            return None
        new_name = self.rename_entry.get().strip()
        self.cancelInlineRename()
        if not new_name or new_name in ('.', '..') or os.path.basename(new_name) != new_name:
            messagebox.showerror('Error Renaming Node', 'Enter a node name, not a path.')
            return None
        parent_path = os.path.dirname(os.path.normpath(old_path))
        if parent_path == '.':
            parent_path = ''
        new_path = os.path.join(parent_path, new_name) if parent_path else new_name
        if os.path.normcase(os.path.normpath(new_path)) == os.path.normcase(os.path.normpath(old_path)):
            return None
        self.renameFileAndDir(node, old_path, new_path)

    def renameNode(self):
        node = self.selected_node
        if not node:
            return None
        self.cancelMoveNode()
        self.cancelInlineRename()
        node_path = self.get_node_path(node)
        bbox = self.tree.bbox(node, '#0')
        if not bbox:
            self.tree.widget.see(node)
            self.window.update_idletasks()
            bbox = self.tree.bbox(node, '#0')
        if not bbox:
            return None

        x, y, width, height = bbox
        entry = ttk.Entry(self.tree.widget, font=self.tkinter_font)
        entry.insert(0, self.tree.item(node)['text'])
        entry.select_range(0, 'end')
        entry.place(x=x, y=y, width=max(width, 100), height=height)
        self.rename_entry = entry
        entry.bind('<Return>', lambda _: self.finishInlineRename(node, node_path))
        entry.bind('<Escape>', lambda _: self.cancelInlineRename())
        entry.bind('<FocusOut>', lambda _: self.finishInlineRename(node, node_path))
        entry.focus_set()
        return 'break'
    
    def replaceTextSelectionForPaste(self):
        """Remove the selected content and place the cursor at its start."""
        if not self.text.tag_ranges('sel'):
            return

        paste_index = self.text.index('sel.first')
        self.text.delete('sel.first', 'sel.last')
        self.text.mark_set('insert', paste_index)

    def pasteFromClipboard(self, event=None):
        self.clip.open_clipboard()
        try:
            clip_rtf_data = self.clip.get_clipboard()
            get_file_paths = getattr(self.clip, 'get_file_paths', lambda: [])
            clipboard_files = get_file_paths() if clip_rtf_data is None else []
        finally:
            self.clip.close_clipboard()
        
        if clip_rtf_data == None: # fallback on grabbing very normal images from clipboard
            if clipboard_files:
                self.replaceTextSelectionForPaste()
                for path in clipboard_files:
                    try:
                        with Image.open(path) as opened_image:
                            self.createEmbeddedImage('insert', opened_image)
                    except (OSError, ValueError):
                        try:
                            with open(path, 'rb') as source:
                                self.createEmbeddedFile('insert', os.path.basename(path), source.read())
                        except OSError as exc:
                            messagebox.showerror('Could not paste attachment', str(exc))
                return 'break'

            clipimg = ImageGrab.grabclipboard()
            #print(clipimg)
            if clipimg == None: # if no image on clipboard, ignore
                return None
            
            if type(clipimg) == list:
                self.replaceTextSelectionForPaste()
                for path in clipimg:
                    try:
                        with Image.open(path) as opened_image:
                            self.createEmbeddedImage('insert', opened_image)
                    except (OSError, ValueError):
                        with open(path, 'rb') as source:
                            self.createEmbeddedFile('insert', os.path.basename(path), source.read())
                
                return 'break'
            
            self.replaceTextSelectionForPaste()
            self.createEmbeddedImage('insert', clipimg)
        else: # rtf data on the clipboard
            # parse it and display it as normal, to facilitate being able to copy-paste within SuperText
            parsed_clip = RTFParser(clip_rtf_data).parseme()
            self.replaceTextSelectionForPaste()
            paste_mark = '__paste_insert'
            self.text.mark_set(paste_mark, 'insert')
            self.text.mark_gravity(paste_mark, 'right')
            try:
                self.displayNestedRTFStructure(parsed_clip, paste_mark)
            finally:
                self.text.mark_unset(paste_mark)
            #print(parsed_clip)
        return 'break'

    def copyFromClipboard(self, event=None):
        if not self.text.tag_ranges('sel'):
            return None
        
        sel_start = self.text.index('sel.first')
        sel_end = self.text.index('sel.last')
        
        selected_text = self.text.dump(sel_start, sel_end)
        
        text_in_selection = self.dumpTextWithoutAlignmentPadding(selected_text)
        plain_text_in_selection = self.plainTextForClipboard(text_in_selection)
        imgs_in_selection = [x[1] for x in selected_text if 'image' in x]

        ibytes = io.BytesIO()
        #shifted_img = ImageTk.getimage(self.tkinter_imagelist[0])
        #shifted_img.save(ibytes, 'DIB')
        
        self.clip.open_clipboard()
        # this is needed for unknown reasons, the docs say this should lose the handle
        self.clip.clear_clipboard()

        if len(text_in_selection) > 0:
            self.setClipboardPlainText(plain_text_in_selection)
            self.clip.set_clipboard(
                self.convertToRTF(sel_start, sel_end).encode('utf-8'),
                self.clip.RTF_NO_OBJ,
            )

        if len(text_in_selection) == 0 and len(imgs_in_selection) > 0:
            for embedded_image in imgs_in_selection:
                tkimg = self.getPhotoImageForEmbeddedImage(embedded_image)
                if tkimg is not None:
                    ImageTk.getimage(tkimg).save(ibytes, 'DIB')
                    self.clip.set_clipboard(ibytes.getvalue(), self.clip.BITMAP)
                    break

        self.clip.close_clipboard()
        #self.window.clipboard_clear()
        #clipboard_paste(ibytes.getvalue())
        
        return 'break'

    def cutTextSelection(self, event=None):
        """Copy the selected rich content and remove it from the document."""
        if not self.text.tag_ranges('sel'):
            return None

        sel_start = self.text.index('sel.first')
        sel_end = self.text.index('sel.last')
        self.copyFromClipboard(event)
        self.text.delete(sel_start, sel_end)
        self.scheduleToolbarStyleUpdate()
        self.scheduleCenteredTextLayoutRefresh()
        self.scheduleTableLayoutRefresh()
        return 'break'
    
    # find the node with the path specified
    def find_self(self, file):
        # path portion
        segments = file.split(os.sep)
        
        if len(segments) == 0:
            return ''
        
        filename = os.path.basename(file)[:-4]
        
        children = dict([[self.tree.item(x)['text'], x] for x in self.tree.get_children()])
        
        for s in segments:
            parent = (children := children[s])
            children = dict([[self.tree.item(x)['text'], x] for x in self.tree.get_children(children)])
        
        return parent
    
    # find the parent of a file relative to the node tree
    # return '' if no parent
    def find_parent(self, file):
        # path portion
        segments = file.split(os.sep)[0:-1]
        if len(segments) == 0:
            return ''
        
        return self.find_self(os.sep.join(segments))
    
    # get the parent of a node in a node tree
    # node->node
    def get_node_parent(self, node):
        return self.tree.parent(node)
    
    # get the full file path of the node from the node itself
    def get_node_path(self, node):
        if len(node) == 0:
            return ''
        basepath = self.tree.item(node)['text']
        while (node := self.get_node_parent(node)) != '':
            upper_node = self.tree.item(node)['text']
            basepath = upper_node + os.sep + basepath
        
        return basepath
    
    # new lazy-loading node tree population
    # go 1 extra step to stop false-nodes being shown
    def populateNodeTree(self, startPath='', currentNode=None):
        if startPath == '':
            self.tkintertree_itemid = 0 # reset the tkinter tree item id counter
            startPath = self.nodeDir
        
        # always clear item ids when deleting nodes
        children_of_child = self.get_all_children(currentNode)
        for c in children_of_child:
            self.item_ids.remove(int(c.split('_')[1]))

        self.tree.delete(*self.tree.get_children(currentNode)) # clear current tree
        files = glob.glob(os.path.join(startPath, '*.rtf'))
        files_second_level = glob.glob(os.path.join(startPath, '**', '*.rtf'))
        files = files + files_second_level
        
        files = [os.path.relpath(os.path.abspath(os.path.normpath(x)), self._node_root_path()) for x in files]
        
        old_tree_len = len(self.tree.get_children())
        for fi in files:
            self.tree.insert(self.find_parent(fi), 'end', text=os.path.basename(fi)[:-4], value='', iid=self.getNextTkinterItemId())
        
        if old_tree_len == 0 and len(self.tree.get_children()) > 0:
            self.selected_node = self.tree.get_children()[0]
            self.tree.selection_set(self.selected_node) # default select first thing in tree
            self.tree.focus(item=self.selected_node) # focus as well
        elif not self.tree.get_children():
            self.selected_node = ()

if __name__ == '__main__':
    dev_version_number = 1.16
    print(f"SuperText Version {dev_version_number}")
    RTFWindow()
