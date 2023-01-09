
import tkinter as tk
from tkinter import ttk

# This class exists to create a scrollable text object
# which is just a multi-line text box with a scrollbar taped to it

class ScrollableText(tk.Frame):
  def __init__(self, parent, **kwargs):
    # initalize this object to have the same properties as an
    # initalized tk.Frame
    # and initialize the frame with respect to the parent tkinter object
    super().__init__(parent)
    
    # needed for proper reactive UI resizing
    self.grid_rowconfigure(0, weight=1)
    self.grid_columnconfigure(0, weight=1)
    
    # pass styling arguments to the text
    text = tk.Text(self, **kwargs, wrap='word')
    text.grid(row=0, column=0, sticky='nsew') # fill available space with text
    
    # set up scrollbar to scroll the text area
    scrolly = tk.Scrollbar(self, command=text.yview)
    scrolly.grid(row=0, column=1, sticky='nse') # won't auto-expand because column isn't configured with a weight
    text.config(yscrollcommand=scrolly.set) # sets the scrollbar to match where the text is scrolled to
    
    # set some functions to be that of text because the text object is the main one being interacted with
    self.configure = text.configure
    self.delete = text.delete
    self.insert = text.insert
    self.get = text.get
    self.see = text.see
    self.dump = text.dump
    self.bind = text.bind
    self.image_create = text.image_create
    self.index = text.index
    self.tag_ranges = text.tag_ranges

# Scrollable treeview, to add horizontal and vertical scrolling to the tree view
class ScrollableTreeView(tk.Frame):
  def __init__(self, parent, width, **kwargs):
    # initalize this object to have the same properties as an
    # initalized tk.Frame
    # and initialize the frame with respect to the parent tkinter object
    super().__init__(parent, width=width)
    
    # stops treeview from expanding the containing frame
    self.pack_propagate(0)
    self.grid_propagate(0)
    
    # needed for proper reactive UI resizing
    self.grid_rowconfigure(0, weight=1)
    self.grid_columnconfigure(1, weight=1)
    
    tree = ttk.Treeview(self, **kwargs)
    tree.grid(row=0, column=1, sticky='nsew')
    
    # set up vertical scrollbar to scroll the treeview
    scrolly = tk.Scrollbar(self, command=tree.yview)
    scrolly.grid(row=0, column=0, sticky='nsw') # won't auto-expand because column isn't configured with a weight
    tree.config(yscrollcommand=scrolly.set) # sets the scrollbar to match where the text is scrolled to
    
    # set up horizontal scrollbar to scroll the treeview
    scrollx = tk.Scrollbar(self, command=tree.xview, orient='horizontal')
    scrollx.grid(row=1, column=1, sticky='sew') # won't auto-expand because column isn't configured with a weight
    tree.config(xscrollcommand=scrollx.set) # sets the scrollbar to match where the text is scrolled to
    
    self.heading = tree.heading
    self.column = tree.column
    self.bind = tree.bind
    self.delete = tree.delete
    self.get_children = tree.get_children
    self.insert = tree.insert
    self.item = tree.item
    self.selection_set = tree.selection_set
    self.selection = tree.selection
    self.parent = tree.parent
    self.identify = tree.identify
    self.selection_remove = tree.selection_remove
    self.configure = tree.configure
    self.xview = tree.xview
    self.move = tree.move
    self.focus = tree.focus