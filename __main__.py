# GUI utilities
# Tkinter
# Chosen because Tkinter is shipped standard with Python and does not require GTK
# or anything complex to get it running
import tkinter as tk
from tkinter import colorchooser, messagebox, font, ttk

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
import shutil

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

# this is the meat of the program, that joins together the uicomponents, RTF parser, and INI config into one functional UI and software
class RTFWindow:
    ACTION_QUEUE_POLL_MS = 10
    FORMAT_TAG_PREFIX = "rtf_style_"
    DEFAULT_FONT_FAMILY = "Consolas"
    DEFAULT_FONT_SIZE = 12
    DEFAULT_TEXT_COLOR = None

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
        self.openFile = '' # holds the currently open file for easy saving etc.
        self.tkinter_imagelist = [] # tkinter has a garbage collector bug where images need to be kept in a list to prevent them being garbage collected

        # 1 pixel = 15 twips
        self.rtf_img_factor = 15

        self.font_table = {0: self.DEFAULT_FONT_FAMILY}
        self.color_table = {0: self.DEFAULT_TEXT_COLOR}
        self.style_tags = {}
        self.style_tag_names = {}
        self.style_tag_counter = 0

        # track if a UI popup is open or not to prevent spawning multiple windows
        self.UI_popup = None
        
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
        
        self.tkinter_font = tk.font.Font(family='Consolas', size=12)
        
        # window design goes here
        
        # panedwindow allows dynamic resize by user
        panedWin = ttk.PanedWindow(self.window, orient='horizontal')
        panedWin.pack(fill='both', expand=True)

        # first the file tree
        treeFrame = tk.Frame(panedWin)
        #treeFrame.grid(row=0, column=0, sticky='nsw') # not 100% fill
        panedWin.add(treeFrame)
        
        # buttons to manipulate tree
        buttonFrame = tk.Frame(treeFrame)
        buttonFrame.pack(anchor='w')
        
        # everything is stacked to the left
        tk.Button(buttonFrame, text='update', command=self.populateNodeTree).pack(side='left')
        tk.Button(buttonFrame, text='new', command=self.createNewNode).pack(side='left')
        tk.Button(buttonFrame, text='rename', command=self.renameNode).pack(side='left')
        tk.Button(buttonFrame, text='delete', command=self.deleteNode).pack(side='left')
        
        # browse is used because multiselect is hard, and this works fine for a tree-based text editor
        
        ttk.Style().configure('Treeview', font=self.tkinter_font) # set the font of the treeview to a known font, for horisontal scroll adjust
        
        self.tkintertree_itemid = 0


        # moving the width from a minimum width, to a starting width
        self.tree = ScrollableTreeView(treeFrame, width=230, selectmode='browse')
        self.tree.pack(anchor='w', fill='both', expand=True) # treeview is anchored to the west
        self.tree.heading('#0', text='Nodes', anchor='w') # set the default heading name and width
        self.tree.column('#0', anchor='w')
        
        # bind a callback for horizontal scroll adjustment
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.actionQueue.put(PrioritizedItem(3, lambda : self.treeOpenClose(e), "treeOpenClose")))
        # selecting a node will load it from a source file
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.actionQueue.put(PrioritizedItem(5, lambda : self.tryReadShowRTF(e), "tryReadShowRTF")), add='+')
        
        # double click toggles selection on and off, to allow for making new root nodes
        # this makes sense to run before showing the RTF file. in practice it seems like it gets into the queue first so runs first anyways
        self.tree.bind('<Double-1>', lambda e: [self.actionQueue.put(PrioritizedItem(4, lambda : self.treeSelectUnselect(e), "treeSelectUnselect")), 'break'][1])

        # bind a callback for treeview open so that lazy loading is possible
        # this is lower priority than lazyUnload so then it always will run after lazyUnload if they are both in the queue
        self.tree.bind('<<TreeviewOpen>>', lambda e: self.actionQueue.put(PrioritizedItem(2, lambda : self.lazyloadNodes(e), "lazyloadNodes")))
        # treeview close is used to help save memory on lazy-load by clearing old stuff
        self.tree.bind('<<TreeviewClose>>', lambda e: self.actionQueue.put(PrioritizedItem(1, lambda : self.lazyUnloadNodes(e), "lazyUnloadNodes")))

        # end file tree
        
        # start textarea
        textFrame = tk.Frame(panedWin)
        #textFrame.grid(row=0, column=1, sticky='nsew')
        panedWin.add(textFrame)
        
        # control bar is here, only save button for now
        controlFrame = tk.Frame(textFrame)
        controlFrame.pack(fill='x', anchor='w')

        tk.Button(controlFrame, text='save', command=self.saveRTF).pack(side='left')

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

        tk.Label(controlFrame, text='Font').pack(side='left', padx=(12, 2))
        self.font_family_var = tk.StringVar(value=self.DEFAULT_FONT_FAMILY)
        self.font_family_box = ttk.Combobox(
            controlFrame,
            textvariable=self.font_family_var,
            values=font_values,
            width=24,
            state='readonly',
        )
        self.font_family_box.pack(side='left')
        self.font_family_box.bind(
            '<<ComboboxSelected>>',
            lambda _: self.applySelectedFontFamily(),
        )

        tk.Label(controlFrame, text='Size').pack(side='left', padx=(8, 2))
        self.font_size_var = tk.IntVar(value=self.DEFAULT_FONT_SIZE)
        self.font_size_spinbox = tk.Spinbox(
            controlFrame,
            from_=6,
            to=96,
            width=4,
            textvariable=self.font_size_var,
            command=self.applySelectedFontSize,
        )
        self.font_size_spinbox.pack(side='left')
        self.font_size_spinbox.bind('<Return>', lambda _: self.applySelectedFontSize())
        self.font_size_spinbox.bind('<FocusOut>', lambda _: self.applySelectedFontSize())

        self.text_color_button = tk.Button(
            controlFrame,
            text='Text color',
            command=self.chooseTextColorForSelection,
        )
        self.text_color_button.pack(side='left', padx=(8, 0))

        self.bold_button = tk.Button(
            controlFrame,
            text='B',
            width=3,
            font=(self.DEFAULT_FONT_FAMILY, self.DEFAULT_FONT_SIZE, 'bold'),
            command=self.toggleBoldForSelection,
        )
        self.bold_button.pack(side='left', padx=(8, 0))

        self.italic_button = tk.Button(
            controlFrame,
            text='I',
            width=3,
            font=(self.DEFAULT_FONT_FAMILY, self.DEFAULT_FONT_SIZE, 'italic'),
            command=self.toggleItalicForSelection,
        )
        self.italic_button.pack(side='left', padx=(2, 0))
        
        self.text = ScrollableText(textFrame, font=self.tkinter_font)
        self.text.pack(fill='both', expand='True') # text fills entire remaining space
        
        self.text.bind('<Control-v>', self.pasteFromClipboard) # bound to enable clipboard pasting
        self.text.bind('<Control-c>', self.copyFromClipboard) # bound to enable clipboard rich copying
        self.text.bind('<Control-b>', lambda _: self.toggleBoldForSelection())
        self.text.bind('<Control-i>', lambda _: self.toggleItalicForSelection())
        self.text.bind('<KeyRelease>', self.scheduleToolbarStyleUpdate, add='+')
        self.text.bind('<ButtonRelease-1>', self.scheduleToolbarStyleUpdate, add='+')
        self.text.bind('<<Selection>>', self.scheduleToolbarStyleUpdate, add='+')
        
        self.text.bind('<Control-x>', lambda e: [self.copyFromClipboard(e), self.text.delete(self.text.index('sel.first'), self.text.index('sel.last'))][0]) # bound to enable clipboard rich cutting
        
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
    
    def LogWithDateTime(self, *strstolog : str):
        print(datetime.datetime.now(), ':', *strstolog)

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
        }

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

    def getToolbarStyleIndex(self):
        if self.text.tag_ranges('sel'):
            return self.text.index('sel.first')

        index = self.text.index('insert')
        if self.text.compare(index, '>=', 'end'):
            index = self.text.index('end-1c')

        return index

    def scheduleToolbarStyleUpdate(self, event=None):
        self.window.after_idle(self.updateToolbarStyleFromSelection)
        return None

    def updateToolbarStyleFromSelection(self):
        style = self.getTextStyleAt(self.getToolbarStyleIndex())

        self.font_family_var.set(style["font_family"])
        self.font_size_var.set(style["font_size"])

        self.bold_button.configure(relief='sunken' if style["bold"] else 'raised')
        self.italic_button.configure(relief='sunken' if style["italic"] else 'raised')

        return None

    def insertStyledText(self, index, text, style):
        tag = self.getStyleTag(style)
        if tag is None:
            self.text.insert(index, text)
        else:
            self.text.insert(index, text, (tag,))

    def removeStyleTags(self, start, finish):
        for tag in list(self.style_tags):
            self.text.tag_remove(tag, start, finish)

    def selectedTextRange(self):
        if not self.text.tag_ranges('sel'):
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

        return 'break'

    def applyStylePropertyToSelection(self, property_name, value):
        selected_range = self.selectedTextRange()
        if selected_range is None:
            return None

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

    def toggleStylePropertyForSelection(self, property_name):
        selected_range = self.selectedTextRange()
        if selected_range is None:
            return None

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

    def chooseTextColorForSelection(self):
        selected_range = self.selectedTextRange()
        if selected_range is None:
            return None

        selected_color = colorchooser.askcolor(
            color=self.getTextStyleAt(selected_range[0])["color"],
            parent=self.window,
            title='Choose text color',
        )
        if selected_color[1] is None:
            return None

        return self.applyStylePropertyToSelection("color", selected_color[1])
        
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

    def displayRTFImageGroup(self, structure):
        img_buildout_hex = self.extractRTFImageHex(structure)

        if img_buildout_hex == '':
            return None

        try:
            imgdata = io.BytesIO(bytes.fromhex(img_buildout_hex.replace('\r', '').replace('\n', '').replace(' ', '')))
            img = Image.open(imgdata)
        except (OSError, ValueError) as exc:
            print(f'ERROR: Could not load embedded image: {exc}')
            return None

        self.tkinter_imagelist += [ImageTk.PhotoImage(img)]
        self.text.image_create('end', image=self.tkinter_imagelist[-1])

        return None

    def applyRTFCommandToStyle(self, command, style):
        if command == 'par':
            self.insertStyledText('end', '\n', style)
            return style

        if command == 'plain':
            return self.defaultTextStyle()

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

    def displayNestedRTFStructure(self, structure):
        self.font_table = self.parseRTFFontTable(structure)
        self.color_table = self.parseRTFColorTable(structure)
        self._displayNestedRTFStructure(structure, self.defaultTextStyle())

    def _displayNestedRTFStructure(self, structure, style):
        first_command = self.firstRTFCommand(structure)
        if first_command in {'fonttbl', 'colortbl'}:
            return None

        if first_command == 'pict':
            return self.displayRTFImageGroup(structure)

        current_style = style.copy()
        for token in structure:
            if isinstance(token, list):
                self._displayNestedRTFStructure(token, current_style.copy())
                continue

            token_type, token_value = token
            if token_type in {'TEXT', 'CMDPARAM'}:
                self.insertStyledText('end', token_value, current_style)
            elif token_type == 'RTFCMD':
                current_style = self.applyRTFCommandToStyle(token_value, current_style)
            else:
                print('ERROR: UNKNOWN PARSE TOKEN TO DISPLAY')
                print(token)

        return None

    def tryReadShowRTF(self, event): # event is not used
        self.text.delete('1.0', 'end') # delete all text in textbox currently
        
        selection = self.selected_node = self.tree.selection()[0] if len(self.tree.selection()) != 0 else ()
        
        if len(selection) == 0: # if nothing is selected
            return None

        sel_path = self.get_node_path(selection)
        
        if sel_path == '':
            return None
        
        node_path = self.resolveNodePath(sel_path) + '.rtf'
        
        try:
            with open(node_path, 'r', encoding='utf-8') as fi:
                data = fi.read()
        except UnicodeDecodeError:
            with open(node_path, 'r') as fi:
                data = fi.read()
        except OSError as exc:
            self.openFile = ''
            messagebox.showerror('Error Reading Node', f'Could not read node file: {exc}')
            return None

        # parse the RTF using the RTF parser
        try:
            rt = RTFParser(data).parseme()
        except RTFParseError as exc:
            self.openFile = ''
            messagebox.showerror('Error Reading Node', f'Could not parse node RTF: {exc}')
            return None

        # verify the header matches the expected for an RTF that this program can read
        if not self.isSupportedRTF(rt):
            self.openFile = ''
            messagebox.showerror('Error Reading Node', 'Unsupported RTF header')
            return None
        
        # all header checks have passed
        self.openFile = node_path
        
        # clear existing images from image list
        self.tkinter_imagelist = []

        self.displayNestedRTFStructure(rt)

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

        header = r'{\rtf1\ansi\pard ' + r'{\fonttbl' + font_table + '}'

        if color_ids:
            colors_by_id = sorted(color_ids.items(), key=lambda item: item[1])
            color_table = ';'
            for color, _ in colors_by_id:
                red = int(color[1:3], 16)
                green = int(color[3:5], 16)
                blue = int(color[5:7], 16)
                color_table += rf'\red{red}\green{green}\blue{blue};'
            header += r'{\colortbl ' + color_table + '}'

        header += rf'\f0\fs{self.DEFAULT_FONT_SIZE * 2} '
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

        return ''.join(commands)

    def currentDumpStyle(self, active_style_tags):
        style = self.defaultTextStyle()
        for tag in active_style_tags:
            if tag in self.style_tags:
                style.update(self.style_tags[tag])
        return style

    def convertDumpToRTFBody(self, textContents):
        body = ''
        font_ids = {self.DEFAULT_FONT_FAMILY: 0}
        color_ids = {}
        active_style_tags = []
        has_formatting = False

        for token_type, token_value, _ in textContents:
            if token_type == 'tagon' and token_value in self.style_tags:
                active_style_tags.append(token_value)
                continue

            if token_type == 'tagoff' and token_value in active_style_tags:
                active_style_tags.remove(token_value)
                continue

            if token_type == 'image':
                real_image = None
                for img in self.tkinter_imagelist:
                    if str(img) == token_value:
                        real_image = img
                        break

                if real_image is None:
                    continue

                ibytes = io.BytesIO()
                shifted_img = ImageTk.getimage(real_image)
                imgx, imgy = shifted_img.size
                shifted_img.save(ibytes, 'PNG')
                body += r'{\pict\pngblip' + rf'\picw{int(imgx*self.rtf_img_factor)}\pich{int(imgy*self.rtf_img_factor)} ' + ibytes.getvalue().hex() + '}'
                continue

            if token_type != 'text':
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
        return any(
            token_type in {'tagon', 'tagoff'} and token_value in self.style_tags
            for token_type, token_value, _ in self.text.dump(start, finish)
        )
    
    # convert a text selection to RTF
    # start to finish of selection
    def convertToRTF(self, start, finish):
        # if no files are open there is nothing to save
        if self.openFile == '': 
            tk.messagebox.showerror(title='No open files to save', message='No open files to save')
            return None
        
        # get the text contents including images
        # tkinter proves "dump" for this
        if finish == 'end':
            finish = 'end-1c'
        textContents = self.text.dump(start, finish)

        body, font_ids, color_ids, has_formatting = self.convertDumpToRTFBody(textContents)

        if has_formatting or color_ids or len(font_ids) > 1:
            data = self.buildRTFHeader(font_ids, color_ids) + body
        else:
            data = self.RTF_HEADER + body

        data = data.strip() # this is cleaner to remove extra whitespace
        data += '}'
        
        return data
    
    # save an RTF file that is open
    def saveRTF(self):
        data = self.convertToRTF('1.0', 'end')
        if data is None:
            return None
        with open(self.openFile, 'w', encoding='utf-8') as fi:
            fi.write(data)
        
        tk.messagebox.showinfo(title='Saved file', message='Saved file')
    
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
        else:
            pass
    
    def renameFileAndDir(self, node, old_path, new_path):
        try:
            old_path_withnodedir = self.resolveNodePath(old_path)
            new_path_withnodedir = self.resolveNodePath(new_path)
            newpath = RenamePathToPath(old_path_withnodedir, new_path_withnodedir)
        except (AssertionError, ValueError) as e:
            messagebox.showerror('Error Renaming Node', 'Error Renaming Node')
            return None

        shutil.move(old_path_withnodedir, newpath)
        shutil.move(old_path_withnodedir + '.rtf', newpath + '.rtf')
        
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
    
    def killUIPopup(self):
        self.UI_popup.destroy()
        self.UI_popup = None
    
    def renameNode(self):
        node = self.selected_node
        if len(node) == 0 or self.UI_popup != None: # if trying to rename no node
            if self.UI_popup != None:
                self.UI_popup.lift()
            return None # do not rename, return None
        
        node_path = self.get_node_path(node)
        
        self.UI_popup = (newWin := tk.Toplevel(self.window))
        newWin.geometry('200x100')
        newWin.resizable(False, False)
        newWin.wm_protocol('WM_DELETE_WINDOW', self.killUIPopup)
        entryBox = tk.Entry(newWin)
        entryBox.insert('end', node_path)
        entryBox.selection_range(sum([len(x) + 1 for x in node_path.split(os.path.sep)[:-1]]), "end")
        entryBox.focus()
        entryBox.place(x=100, y=40, anchor='center')
        
        thebutton = tk.Button(newWin, text='rename', command=lambda: [
        self.renameFileAndDir(node, node_path, entryBox.get()),
        self.killUIPopup()
        ])
        thebutton.place(x=100, y=65, anchor='center')

        entryBox.bind('<Return>', lambda _: thebutton.invoke())
        entryBox.xview_moveto(1)
    
    def pasteFromClipboard(self, event):
        self.clip.open_clipboard()

        clip_rtf_data = self.clip.get_clipboard()

        self.clip.close_clipboard()
        
        if clip_rtf_data == None: # fallback on grabbing very normal images from clipboard
            clipimg = ImageGrab.grabclipboard()
            #print(clipimg)
            if clipimg == None: # if no image on clipboard, ignore
                return None
            
            if type(clipimg) == list:
                for img in clipimg:
                    self.tkinter_imagelist += [ImageTk.PhotoImage(Image.open(img))]
            
                    self.text.image_create('insert', image=self.tkinter_imagelist[-1])
                
                return None
            
            self.tkinter_imagelist += [ImageTk.PhotoImage(clipimg)]
            
            self.text.image_create('insert', image=self.tkinter_imagelist[-1])
        else: # rtf data on the clipboard
            # parse it and display it as normal, to facilitate being able to copy-paste within SuperText
            parsed_clip = RTFParser(clip_rtf_data).parseme()
            self.displayNestedRTFStructure(parsed_clip)
            #print(parsed_clip)
        return 'break'

    def copyFromClipboard(self, event):
        if not self.text.tag_ranges('sel'):
            return None
        
        sel_start = self.text.index('sel.first')
        sel_end = self.text.index('sel.last')
        
        selected_text = self.text.dump(sel_start, sel_end)
        
        text_in_selection = [x[1] for x in selected_text if 'text' in x]
        imgs_in_selection = [x[1] for x in selected_text if 'image' in x]

        ibytes = io.BytesIO()
        #shifted_img = ImageTk.getimage(self.tkinter_imagelist[0])
        #shifted_img.save(ibytes, 'DIB')
        
        self.clip.open_clipboard()
        # this is needed for unknown reasons, the docs say this should lose the handle
        self.clip.clear_clipboard()
        selection_has_formatting = self.rangeHasFormatting(sel_start, sel_end)

        if len(text_in_selection) > 0 and (len(imgs_in_selection) > 0 or selection_has_formatting):
            self.clip.set_clipboard(self.convertToRTF(sel_start, sel_end).encode('utf-8'), self.clip.RTF_NO_OBJ)
        elif len(text_in_selection) > 0:
            try:
                self.clip.set_clipboard(''.join(text_in_selection).encode('ansi'), self.clip.TEXT)
            except UnicodeEncodeError:
                self.clip.set_clipboard(''.join(text_in_selection).encode('utf-16'), self.clip.UNITEXT)
        elif len(imgs_in_selection) > 0:
            for tkimg in self.tkinter_imagelist:
                if str(tkimg) in imgs_in_selection:
                    ImageTk.getimage(tkimg).save(ibytes, 'DIB')
                    self.clip.set_clipboard(ibytes.getvalue(), self.clip.BITMAP)
                    break

        self.clip.close_clipboard()
        #self.window.clipboard_clear()
        #clipboard_paste(ibytes.getvalue())
        
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


    # selects and unselects things on the tree that are clicked on
    def treeSelectUnselect(self, e): # event is used in this one
        selection = self.selected_node
        if len(selection) == 0: # if nothing is selected
            return None
        
        item = self.tree.identify('item', e.x, e.y) # get item clicked on in tree
        if item in selection:
            self.tree.selection_remove(self.selected_node)
            self.selected_node = ()
            self.text.delete('1.0', 'end')
            self.openFile = ''
            return None

if __name__ == '__main__':
    dev_version_number = 1.15
    print(f"SuperText Version {dev_version_number}")
    RTFWindow()
