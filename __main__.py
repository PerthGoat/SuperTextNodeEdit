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

import configparser

# multithreading used to open multiple windows and allow for popup dialogs for renaming
from threading import Thread

# PIL functions used for grabbing the clipboard in a cross-platform way
from PIL import Image, ImageTk, ImageGrab

# user defined functions
# scrollable textboxes
from src.uicomponents import ScrollableText, ScrollableTreeView
# RTF parsing
from src.RTFParser import RTFParser

# for utf-8 printing
import sys

# for image copying
from src.os_specific import Clipboard


# this is the meat of the program, that joins together the uicomponents, RTF parser, and INI config into one functional UI and software
class RTFWindow:
  def __init__(self):
    configFile = 'rtfjournal.ini' # I used this name for no reason other than I liked it
    
    config_dict = configparser.ConfigParser()
    config_dict.read(configFile)
    
    # set up public variables to this class
    self.RTF_HEADER = config_dict['constants']['RTF_HEADER'] + ' ' # read in RTF header
    self.nodeDir = config_dict['constants']['nodeDir'] # read in directory to hold RTF file tree
    self.openFile = '' # holds the currently open file for easy saving etc.
    self.tkinter_imagelist = [] # tkinter has a garbage collector bug where images need to be kept in a list to prevent them being garbage collected
    
    # track if a UI popup is open or not to prevent spawning multiple windows
    self.UI_popup = None
    
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
    
    self.text.bind('<Control-x>', lambda e: [self.copyFromClipboard(e), self.text.delete(self.text.index('sel.first'), self.text.index('sel.last'))][0]) # bound to enable clipboard rich cutting
    
    # end textarea
    
    self.populateNodeTree() # load nodes for file tree on startup
    
    self.window.mainloop()
  
  def getNodePathLength(self, node):
    split_parts = self.get_node_path(node).split(os.sep)
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
    
  def displayNestedRTFStructure(self, structure):
    lastcmd = None
    for i, r in enumerate(structure):
      # if nested stuff exists
      if isinstance(r, list):
        self.displayNestedRTFStructure(r)
        continue
      if r[0] == 'TEXT':
        self.text.insert('end', r[1])
      elif r[0] == 'RTFCMD': # rtf modifier commands
        match(r[1]):
          case 'par': # rtf's version of an explicit newline
            self.text.insert('end', '\n')
          case 'pict': # a picture
            pass # this does nothing, it's chained with another typically
          case 'pngblip':
            if lastcmd[0] != 'RTFCMD' or lastcmd[1] != 'pict':
              print('ERROR: Missing a pict command before the image def!')
          # not implemented commands, ignore
          case 'ansicpg1252':
            print('Not implemented RTFCMD ' + r[1])
          case 'deff0':
            print('Not implemented RTFCMD ' + r[1])
          case 'nouicompat':
            print('Not implemented RTFCMD ' + r[1])
          case 'deflang1033':
            print('Not implemented RTFCMD ' + r[1])
          case 'fnil':
            print('Not implemented RTFCMD ' + r[1])
          case 'fcharset0':
            print('Not implemented RTFCMD ' + r[1])
          case 'viewkind4':
            print('Not implemented RTFCMD ' + r[1])
          case 'uc1':
            print('Not implemented RTFCMD ' + r[1])
          case 'sa200':
            print('Not implemented RTFCMD ' + r[1])
          case 'sl240':
            print('Not implemented RTFCMD ' + r[1])
          case 'slmult1':
            print('Not implemented RTFCMD ' + r[1])
          case 'fs22':
            print('Not implemented RTFCMD ' + r[1])
          case 'lang9':
            print('Not implemented RTFCMD ' + r[1])
          case 'wmetafile8':
            print('Not implemented RTFCMD ' + r[1])
          # header cmds, ignore
          case 'rtf1':
            pass
          case 'ansi':
            pass
          case 'pard':
            pass
          case 'fonttbl': # idc about font for now
            pass
          case 'f0':
            pass
          case 'fswiss':
            pass
          case _: # failout if command is completely not known
            print("ERROR: I see a command but I don't know what it means!")
            print(r)          
      elif r[0] == 'CMDPARAM': # ignore commands with parameters if the command doesn't explicitly consume it
        if lastcmd != None and lastcmd[0] == 'RTFCMD' and lastcmd[1] == 'pngblip': # I should probably be displaying an image here!
          imgdata = io.BytesIO(bytes.fromhex(r[1]))
          img = Image.open(imgdata)

          self.tkinter_imagelist += [ImageTk.PhotoImage(img)]

          self.text.image_create('end', image=self.tkinter_imagelist[-1])
          self.text.insert('end', '\n') # this is the functionality word and wordpad have when encountering images, they add a newline
        if lastcmd == None:
          print('Warning: command parameter without preceding command ' + r[1])
      else:
        print('ERROR: UNKNOWN PARSE TOKEN TO DISPLAY')
        print(r)
      lastcmd = r

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
    rt = RTFParser(data).parseme()

    # verify the header matches the expected for an RTF that this program can read
    assert rt[0][0] == 'RTFCMD' and rt[0][1] == 'rtf1'
    assert rt[1][0] == 'RTFCMD' and rt[1][1] == 'ansi'
    assert rt[2][0] == 'RTFCMD' and rt[2][1] == 'pard'
    assert len(rt[3]) == 4 # font selection is half-baked
    assert rt[4][0] == 'RTFCMD' and rt[4][1] == 'f0'
    
    # all header checks have passed
    
    # clear existing images from image list
    self.tkinter_imagelist = []

    self.displayNestedRTFStructure(rt)
  
  # convert a text selection to RTF
  # start to finish of selection
  def convertToRTF(self, start, finish):
    # if no files are open there is nothing to save
    if self.openFile == '': 
      tk.messagebox.showerror(title='No open files to save', message='No open files to save')
      return None
    
    # header to save
    data = self.RTF_HEADER
    
    # get the text contents including images
    # tkinter proves "dump" for this
    textContents = self.text.dump(start, finish)
    
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
    data = self.convertToRTF('1.0', 'end')
    with open(self.openFile, 'w', encoding='utf-8') as fi:
      fi.write(data)
    
    tk.messagebox.showinfo(title='Saved file', message='Saved file')
  
  def createNewNode(self):
    sel = self.tree.selection()
    
    newNodeName = f'newNode{len(self.tree.get_children(sel))}'
    
    path = self.nodeDir + self.get_node_path(sel) + os.sep + newNodeName
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
  
  def killUIPopup(self):
    self.UI_popup.destroy()
    self.UI_popup = None
  
  def renameNode(self):
    node = self.tree.selection()
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
    entryBox.place(x=100, y=40, anchor='center')
    
    tk.Button(newWin, text='rename', command=lambda: [
    self.renameFileAndDir(node, node_path, entryBox.get()),
    self.killUIPopup()
    ]).place(x=100, y=65, anchor='center')
  
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
    if len(text_in_selection) > 0 and len(imgs_in_selection) > 0:
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
    segments = file.split(os.sep)[1:-1]

    if len(segments) == 0:
      return ''
    
    return self.find_self(os.sep.join(segments))
  
  # get the parent of a node in a node tree
  # node->node
  def get_node_parent(self, node):
    return self.tree.parent(node)
  
  # get the full file path of the node from the node itself
  def get_node_path(self, node):
    basepath = self.tree.item(node)['text']
    while (node := self.get_node_parent(node)) != '':
      upper_node = self.tree.item(node)['text']
      basepath = upper_node + os.sep + basepath
    
    return basepath
  
  # populate node tree with rtf files
  def populateNodeTree(self):
    self.tree.delete(*self.tree.get_children()) # clear current tree
    files = glob.glob(os.path.join(self.nodeDir, '**', '*.rtf'), recursive=True)
    
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
  dev_version_number = 1.02
  print(f"SuperText Version {dev_version_number}")
  RTFWindow()