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
from uicomponents import ScrollableText
# RTF parsing
from RTFParser import RTFParser
# ini parsing
from iniconfig import INIConfig

# for utf-8 printing
import sys

# for image copying
from os_specific import Clipboard

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
    self.tree = ttk.Treeview(treeFrame, selectmode='browse')
    self.tree.pack(anchor='w', fill='y', expand=True) # treeview is anchored to the west, allowed to expand along y axis only
    self.tree.heading('#0', text='Nodes') # set the default heading name and width
    self.tree.column('#0', width=200)
    
    # selecting a nodfe will load it from a source file
    self.tree.bind('<<TreeviewSelect>>', self.tryReadShowRTF)
    
    # double click toggles selection on and off, to allow for making new root nodes
    self.tree.bind('<Double-1>', self.treeSelectUnselect)
    
    # end file tree
    
    # start textarea
    textFrame = tk.Frame(self.window)
    textFrame.grid(row=0, column=1, sticky='nsew')
    
    # control bar is here, only save button for now
    tk.Button(textFrame, text='save', command=self.saveRTF).pack()
    
    self.text = ScrollableText(textFrame, font=tk.font.Font(family='Consolas', size=12))
    self.text.pack(fill='both', expand='True') # text fills entire remaining space
    
    self.text.bind('<Control-v>', self.pasteFromClipboard) # bound to enable clipboard pasting
    self.text.bind('<Control-c>', self.copyFromClipboard) # bound to enable clipboard rich copying
    
    # end textarea
    
    self.populateNodeTree() # load nodes for file tree on startup
    
    self.window.mainloop()
  
  def tryReadShowRTF(self, event): # event is not used
    self.text.delete('1.0', 'end') # delete all text in textbox currently
    
    selection = self.tree.selection() # get selection
    s_item = self.tree.item(selection) # get the item, which has the values the item contains
    
    if len(s_item['values']) == 0: # if for some reason there are no values attached to the node
      return None # return None to fail gracefully
    
    self.openFile = s_item['values'][0] # get the filename from the node
    
    try:
      with open(self.openFile, 'r', encoding='utf-8') as fi:
        data = fi.read()
    except UnicodeDecodeError:
      with open(self.openFile, 'r') as fi:
        data = fi.read()
    # parse the RTF using the RTF parser
    rt = RTFParser(data).parse()
    
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
      else: # nuclear mode, put out whatever got read to parse as best as possible
        self.text.insert('end', r)
  
  # convert a text selection to RTF
  def convertToRTF(self):
    # if no files are open there is nothing to save
    if self.openFile == ' ': 
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
        data += t[1].replace('\n', r'{\par }')
    
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
    
    if len(sel) != 0:
      parent = self.tree.item(sel)
      path = parent['values'][0][:-4] # remove .rtf
    else: # default to no nesting
      path = self.nodeDir
    
    # new node is a product of the number of children to keep them varied and prevent overlap
    newNodeName = f'newNode{len(self.tree.get_children(self.tree.selection()))}'
    
    newPath = f'{path}/{newNodeName}'
    
    newPath = newPath.replace('//','/') # get rid of trailing slash on roots
    
    # create the new dir to go with the new file
    os.makedirs(newPath, exist_ok=True)
    # create new RTF with basics, just the header
    with open(newPath + '.rtf', 'w') as fi:
      fi.write(self.RTF_HEADER + '}')
    
    self.tree.insert(self.tree.selection(), 'end', text=newNodeName, value=newPath+'.rtf')
  
  def deleteNode(self):
    parent = self.tree.selection()
    parentItem = self.tree.item(parent)
    path = parentItem['values'][0][:-4]
    
    result = tk.messagebox.askquestion('Delete', f'Are you sure you want to delete {parentItem["text"]}?')
    
    if result == 'yes':
      self.tree.delete(*self.tree.get_children(parent))
      self.tree.delete(parent)
      
      shutil.rmtree(path)
      os.remove(path + '.rtf')
    else:
      pass
  
  def renameFileAndDir(self, entryBox):
    folderpath = self.nodeDir + entryBox.get()
    
    if not os.path.isdir('/'.join(folderpath.split('/')[:-1])):
      tk.messagebox.showerror(title='Non-existing tree', message="Can't move node to non-existing tree.")
      return None
    
    shutil.move(self.openFile[:-4], folderpath)
    shutil.move(self.openFile, folderpath + '.rtf')
  
  def renameNode(self):
    node = self.tree.selection()
    if len(node) == 0: # if trying to rename no node
      return None # do not rename, return None
    
    print(self.tree.item(node))
    exit(0)
    newWin = tk.Toplevel(self.window)
    entryBox = tk.Entry(newWin)
    entryBox.insert('end', self.openFile[len(self.nodeDir):-4])
    entryBox.pack()
    
    # refreshes because it is easier
    tk.Button(newWin, text='rename', command=lambda: [
    self.renameFileAndDir(entryBox),
    self.populateNodeTree(),
    newWin.destroy()
    ]).pack()
  
  def pasteFromClipboard(self, event):
    clipimg = ImageGrab.grabclipboard()
    
    if clipimg == None: # if no image on clipboard, ignore
      return None
    
    self.tkinter_imagelist += [ImageTk.PhotoImage(clipimg)]
    
    self.text.image_create('insert', image=self.tkinter_imagelist[-1])
  
  def copyFromClipboard(self, event):
    #print('copy')
    #print(event)
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
    
    self.clip.set_clipboard(' '.join(text_in_selection).encode('utf-8'), self.clip.TEXT)
    self.clip.close_clipboard()
    
    #self.window.clipboard_clear()
    #clipboard_paste(ibytes.getvalue())
    
    
    
    return 'break'
  
  # find the parent of a file relative to the node tree
  # return '' if no parent
  def find_parent(self, node):
    upper_dir = node.split('/')
    
    if len(upper_dir) == 1: # then it is a root
      return ''
    
    upper_dir = upper_dir[-2]
    for n in self.tree.get_children():
      t_folder = self.tree.item(n)['text'][:-4]
      if t_folder == upper_dir:
        return n
    
    return ''
  
  # get the parent of a node in a node tree
  # node->node
  def get_node_parent(self, node):
    return self.tree.parent(node)
  
  # get the full file path of the node from the node itself
  def get_node_path(self, node):
    basepath = self.tree.item(node)['text']
    while (node := self.get_node_parent(node)) != '':
      upper_node = self.tree.item(node)['text'][:-4]
      basepath = upper_node + '/' + basepath
    
    return basepath
  
  # populate node tree with rtf files
  def populateNodeTree(self):
    self.tree.delete(*self.tree.get_children()) # clear current tree
    files = glob.glob(f'{self.nodeDir}**/*.rtf', recursive=True)
    
    files = [x.replace(self.nodeDir, '') for x in files]
    
    #self.tree.insert(self.find_parent(files[3]), 'end', text=os.path.basename(files[3]), value='')
    
    #print(self.find_parent(files[12]))
    
    #self.tree.insert(self.find_parent(files[12]), 'end', text=os.path.basename(files[12]), value='')
    
    for fi in files:
      self.tree.insert(self.find_parent(fi), 'end', text=os.path.basename(fi), value='')
    
    
    
    #exit(0)
    '''fi = files[3]
    
    no = self.tree.insert('', 'end', text=os.path.basename(fi), value='')
    
    #print(self.tree.get_children())
    
    fi2 = files[12]
    parent = self.find_parent(fi2)
    ni = self.tree.insert(parent, 'end', text=os.path.basename(fi2), value='')'''
    
    #print(self.get_node_parent(no) == '')
    
    #print(self.get_node_path(ni))
    
    #print(ni)
    #exit(0)
    
    #
    
    #print(fi2)
    
    #for fi in files:
    #exit(0)
    #insert_paths = {self.nodeDir[:-1]: ''} # allows objects to be stored for the tree to be built in tkinter
    '''for fi in files:
      node_file_only = os.path.basename(fi)
      nodeName = fi[:-4]
      insobj = self.tree.insert('', 'end', text=nodeName.split('/')[-1], value=node_file_only)
      insert_paths[nodeName] = insobj'''
    
    #if len(self.tree.get_children()) > 0:
    #  self.tree.selection_set(self.tree.get_children()[0]) # default select first thing in tree
  
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