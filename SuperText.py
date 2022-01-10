# -*- coding: utf-8 -*-

# GUI utilities
# Tkinter
# Chosen because Tkinter is shipped standard with Python and does not require GTK
# or anything complex to get it running

import tkinter as tk
from tkinter import messagebox, font, ttk

# IO utilities
# these handle parsing, renaming, removing, and moving the various node/file trees
import io
import os
import glob
import shutil

# multithreading used to open multiple windows and allow for popup dialogs for renaming
from threading import Thread

# PIL functions used for grabbing the clipboard in a cross-platform way
from PIL import Image, ImageTk, ImageGrab

# user defined functions
# scrollable textboxes
from uicomponents import ScrollableText, ScrollableTreeView
# RTF parsing
from RTFParser import RTFParser
# ini parsing
from iniconfig import INIConfig

# for utf-8 printing
import sys

# for image copying
from os_specific import Clipboard

from collections import OrderedDict

# this is the meat of the program, that joins together the uicomponents, RTF parser, and INI config into one functional UI and software
class RTFWindow:
  def __init__(self):
    configFile = 'rtfjournal.ini' # I used this name for no reason other than I liked it
    
    config_dict = INIConfig(configFile).readConfig() # read the config dictionary into a variable
    
    # set up public variables to this class
    self.RTF_HEADER = config_dict['constants']['RTF_HEADER'] # read in RTF header
    self.nodeDir = config_dict['constants']['nodeDir'] # read in directory to hold RTF file tree
    self.openFile = '' # holds the currently open file for easy saving etc.
    self.tkinter_imagelist = [] # tkinter has a garbage collector bug where images need to be kept in a list to prevent them being garbage collected
    
    # set up OS specific clipboard for copying images
    self.clip = Clipboard()
    
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
    
    # first the file tree
    treeFrame = tk.Frame(self.window)
    treeFrame.grid(row=0, column=0, sticky='nsw') # not 100% fill
    
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
    
    self.tree = ScrollableTreeView(treeFrame, width=230, selectmode='browse')
    self.tree.pack(anchor='w', fill='y', expand=True) # treeview is anchored to the west, allowed to expand along y axis only
    self.tree.heading('#0', text='Nodes') # set the default heading name and width
    self.tree.column('#0', anchor='w')
    
    # selecting a node will load it from a source file
    self.tree.bind('<<TreeviewSelect>>', self.tryReadShowRTF)
    
    # double click toggles selection on and off, to allow for making new root nodes
    self.tree.bind('<Double-1>', self.treeSelectUnselect)
    
    # bind a second callback for horizontal scroll adjustment
    self.tree.bind('<<TreeviewSelect>>', self.treeOpenClose, add='+')
    
    # end file tree
    
    # start textarea
    textFrame = tk.Frame(self.window)
    textFrame.grid(row=0, column=1, sticky='nsew')
    
    # control bar is here, only save button for now
    tk.Button(textFrame, text='save', command=self.saveRTF).pack()
    
    self.text = ScrollableText(textFrame, font=self.tkinter_font)
    self.text.pack(fill='both', expand='True') # text fills entire remaining space
    
    self.text.bind('<Control-v>', self.pasteFromClipboard) # bound to enable clipboard pasting
    self.text.bind('<Control-c>', self.copyFromClipboard) # bound to enable clipboard rich copying
    
    # end textarea
    
    self.populateNodeTree() # load nodes for file tree on startup
    
    self.window.mainloop()
  
  def getNodePathLength(self, node):
    split_parts = self.get_node_path(node).split('/')
    cur_name = split_parts[-1]
    split_parts = split_parts[:-1]
    tree_item_padding = (len(split_parts) + 1) * 20 # I use 20 here because tkinter arbitrarily choses that as the padding for the treeview
    item_width = self.tkinter_font.measure(cur_name) + tree_item_padding + 5 # 5 is to give the scrollbar more breathing room
    return item_width
  
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
    biggest_node_width = self.visit_whole_tree('')
    # set the treeview tree column to the width of the biggest entry
    # do not stretch so the tree is forced to expand the column outside its maximum width of the frame
    # which gives a horizontal scrollbar
    self.tree.column('#0', width=biggest_node_width, stretch=False)
    
  def tryReadShowRTF(self, event): # event is not used
    self.text.delete('1.0', 'end') # delete all text in textbox currently
    
    selection = self.tree.selection() # get selection
    
    sel_path = self.get_node_path(selection)
    
    if sel_path == '':
      return None
    
    node_path = self.nodeDir + sel_path + '.rtf'
    
    self.openFile = node_path
    
    try:
      with open(self.openFile, 'r', encoding='utf-8') as fi:
        data = fi.read()
    except UnicodeDecodeError:
      with open(self.openFile, 'r') as fi:
        data = fi.read()
    # parse the RTF using the RTF parser
    rt = RTFParser(data).parse()
    #print(rt)
    # verify the header matches the expected for an RTF that this program can read
    assert rt[0] == 'rtf1'
    assert rt[1] == 'ansi'
    assert rt[2] == 'pard'
    assert len(rt[3]) == 4 # font selection is half-baked
    assert rt[4] == 'f0'
    
    # all header checks have passed, now the header can be trimmed off
    trimmed_header_rt = rt[5:]
    # clear existing images from image list
    self.tkinter_imagelist = []
    #print(trimmed_header_rt)
    # go thru each RTF block and do something with it
    for i, r in enumerate(trimmed_header_rt):
      if isinstance(r, list): # only support pngblip pictures and paragraph blocks
        if r[0] == 'pict':
          # check for RTF png header
          assert r[0] == 'pict'
          assert r[1] == 'pngblip'
          
          # put image in textbox
          imgdata = io.BytesIO(bytes.fromhex(r[2]))
          img = Image.open(imgdata)
          
          self.tkinter_imagelist += [ImageTk.PhotoImage(img)]
          
          self.text.image_create('end', image=self.tkinter_imagelist[-1])
          self.text.insert('end', '\n') # this is the functionality word and wordpad have when encountering images, they add a newline
        elif r[0] == 'par' and trimmed_header_rt[i - 1][0] != 'pict':
          if len(r) == 1: # if the paragraph has no text
            self.text.insert('end', '\n') # then it is merely a linebreak
          elif isinstance(r[1], list): # this will never happen with this program because nesting in a par block isn't supported
            pass # either way don't crash, try to keep parsing
          else:
            self.text.insert('end', r[1]) # print out the text defined in the paragraph block
        elif r[0][0] == 'u': # unicode escapes stand alone without a block
          uend = r[0].index('?') # end of unicode char literal in RTF is marked by ?
          unicode_char = chr(int(r[0][1:uend]))
          self.text.insert('end', unicode_char)
          self.text.insert('end', r[0][uend+1:]) # tack on extra text that might have gotten pulled in from the \ declaration
      else: # nuclear mode, put out whatever got read to parse as best as possible
        self.text.insert('end', r)
  
  # convert a text selection to RTF
  def convertToRTF(self):
    # if no files are open there is nothing to save
    if self.openFile == '': 
      tk.messagebox.showerror(title='No open files to save', message='No open files to save')
      return None
    
    # header to save
    data = self.RTF_HEADER
    
    # get the text contents including images
    # tkinter proves "dump" for this
    textContents = self.text.dump('1.0', 'end')
    
    # if there is a trailing newline, remove it
    # tkinter sometimes randomly adds a newline to the text dump
    if textContents[-1][0] == 'text' and textContents[-1][1] == '\n':
      textContents = textContents[:-1]
    
    for i, t in enumerate(textContents):
      if t[0] == 'image':
        real_image = None
        for img in self.tkinter_imagelist:
          if str(img) == t[1]:
            real_image = img
            break
        ibytes = io.BytesIO()
        shifted_img = ImageTk.getimage(real_image)
        shifted_img.save(ibytes, 'PNG')
        data += r'{\pict\pngblip ' + ibytes.getvalue().hex() + '}'
      elif t[0] == 'text':
        txt = t[1]
        txt = txt.replace('\\', '\\\\').replace('{', '\{').replace('}', '\}').replace('\n', r'{\par }') # escape backslash and curly brace
        txt = ''.join([fr"\u{ord(c):04d}?" if ord(c) > 0x7F else c for c in txt]) # if non ASCII, then encode the character for RTF
        data += txt
    
    data = data.strip() # this is cleaner to remove extra whitespace
    data += '}'
    
    return data
  
  # save an RTF file that is open
  def saveRTF(self):
    data = self.convertToRTF()
    with open(self.openFile, 'w', encoding='utf-8') as fi:
      fi.write(data)
    
    tk.messagebox.showinfo(title='Saved file', message='Saved file')
  
  def createNewNode(self):
    sel = self.tree.selection()
    
    newNodeName = f'newNode{len(self.tree.get_children(sel))}'
    
    path = self.nodeDir + self.get_node_path(sel) + '/' + newNodeName
    file_path = path + '.rtf'
    
    # create the new dir to go with the new file
    os.makedirs(path, exist_ok=True)
    # create new RTF with basics, just the header
    with open(file_path, 'w') as fi:
      fi.write(self.RTF_HEADER + '}')
    
    self.tree.insert(sel, 'end', text=newNodeName, value='')
  
  def deleteNode(self):
    parent = self.tree.selection()
    path = self.nodeDir + self.get_node_path(parent)
    result = tk.messagebox.askquestion('Delete', f'Are you sure you want to delete {self.tree.item(parent)["text"]}?')
    
    if result == 'yes':
      self.tree.delete(*self.tree.get_children(parent))
      self.tree.delete(parent)
      
      shutil.rmtree(path)
      os.remove(path + '.rtf')
    else:
      pass
  
  def renameFileAndDir(self, node, old_path, new_path):
    shutil.move(self.nodeDir + old_path, self.nodeDir + new_path)
    shutil.move(self.nodeDir + old_path + '.rtf', self.nodeDir + new_path + '.rtf')
    
    # remove the renamed node and its children to regenerate it w/ the new name
    
    # I use deletion because then rename can be used to relocate children to different node parents
    
    all_children = (children := list(self.tree.get_children(node)))
    
    while len(children) > 0:
      children = sum([list(self.tree.get_children(x)) for x in children if len(x) > 0],[])
      all_children += children
    
    new_paths = [new_path] + [self.get_node_path(x).replace(old_path, new_path, 1) for x in all_children]
    
    self.tree.delete(*self.tree.get_children(node))
    self.tree.delete(node)
    
    for fi in new_paths:
      self.tree.insert(self.find_parent(fi), 'end', text=os.path.basename(fi), value='')
    
    self.tree.selection_set(self.find_self(new_paths[0]))
  
  def renameNode(self):
    node = self.tree.selection()
    if len(node) == 0: # if trying to rename no node
      return None # do not rename, return None
    
    node_path = self.get_node_path(node)
    
    newWin = tk.Toplevel(self.window)
    entryBox = tk.Entry(newWin)
    entryBox.insert('end', node_path)
    entryBox.pack()
    
    # refreshes because it is easier
    tk.Button(newWin, text='rename', command=lambda: [
    self.renameFileAndDir(node, node_path, entryBox.get()),
    newWin.destroy()
    ]).pack()
  
  def pasteFromClipboard(self, event):
    clipimg = ImageGrab.grabclipboard()
    
    if clipimg == None: # if no image on clipboard, ignore
      return None
    
    if type(clipimg) == list:
      for img in clipimg:
        self.tkinter_imagelist += [ImageTk.PhotoImage(Image.open(img))]
    
        self.text.image_create('insert', image=self.tkinter_imagelist[-1])
      
      return None
    
    self.tkinter_imagelist += [ImageTk.PhotoImage(clipimg)]
    
    self.text.image_create('insert', image=self.tkinter_imagelist[-1])
  
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
    self.clip.set_clipboard(self.convertToRTF().encode('utf-8'), self.clip.RTF)
    # write first image in selection to clipboard under the special BITMAP thing
    # just to have something
    for tkimg in self.tkinter_imagelist:
      if str(tkimg) in imgs_in_selection:
        ImageTk.getimage(tkimg).save(ibytes, 'DIB')
        self.clip.set_clipboard(ibytes.getvalue(), self.clip.BITMAP)
        break
    
    try:
      self.clip.set_clipboard(''.join(text_in_selection).encode('ansi'), self.clip.TEXT)
    except UnicodeEncodeError:
      self.clip.set_clipboard(''.join(text_in_selection).encode('utf-16'), self.clip.UNITEXT)
    
    self.clip.close_clipboard()
    
    #self.window.clipboard_clear()
    #clipboard_paste(ibytes.getvalue())
    
    return 'break'
  
  # find the node with the path specified
  def find_self(self, file):
    # path portion
    segments = file.split('/')
    
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
    segments = file.split('/')[:-1]
    
    if len(segments) == 0:
      return ''
    
    return self.find_self('/'.join(segments))
  
  # get the parent of a node in a node tree
  # node->node
  def get_node_parent(self, node):
    return self.tree.parent(node)
  
  # get the full file path of the node from the node itself
  def get_node_path(self, node):
    basepath = self.tree.item(node)['text']
    while (node := self.get_node_parent(node)) != '':
      upper_node = self.tree.item(node)['text']
      basepath = upper_node + '/' + basepath
    
    return basepath
  
  # populate node tree with rtf files
  def populateNodeTree(self):
    self.tree.delete(*self.tree.get_children()) # clear current tree
    files = glob.glob(f'{self.nodeDir}**/*.rtf', recursive=True)
    
    files = [x.replace(self.nodeDir, '') for x in files]
    
    for fi in files:
      self.tree.insert(self.find_parent(fi), 'end', text=os.path.basename(fi)[:-4], value='')
    
    if len(self.tree.get_children()) > 0:
      self.tree.selection_set(self.tree.get_children()[0]) # default select first thing in tree
  
  # selects and unselects things on the tree that are clicked on
  def treeSelectUnselect(self, e): # event is used in this one
    selection = self.tree.selection()
    if len(selection) == 0: # if nothing is selected
      return None
    
    item = self.tree.identify('item', e.x, e.y) # get item clicked on in tree
    if item in selection:
      self.tree.selection_remove(self.tree.selection())
      self.text.delete('1.0', 'end')
      self.openFile = ''
      return 'break'

if __name__ == '__main__':
  sys.stdout.reconfigure(encoding='utf-8')
  RTFWindow()