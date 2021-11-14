
import tkinter as tk

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
    text = tk.Text(self, kwargs)
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