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

# this is the meat of the program, that joins together the uicomponents, RTF parser, and INI config into one functional UI and software
class RTFWindow:
  def __init__(self):
    configFile = 'rtfjournal.ini' # I used this name for no reason other than I liked it
    
    config_dict = RTFParser(configFile).readConfig() # read the config dictionary into a variable
    
    # set up public variables to this class
    self.RTF_HEADER = config_dict['constants']['RTF_HEADER'] # read in RTF header
    self.nodeDir = config_dict['constants']['nodeDir'] # read in directory to hold RTF file tree
    self.openFile = '' # holds the currently open file for easy saving etc.
    self.tkinter_imagelist = [] # tkinter has a garbage collector bug where images need to be kept in a list to prevent them being garbage collected
    
    # create main user interface window
    self.createTkinterWindow()
  
  # main user interface
  def createTkinterWindow(self):
    pass