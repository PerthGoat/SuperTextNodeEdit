import ctypes

# TODO: Add Other Operating Systems for this
import os
import tkinter as tk
import tkinter.messagebox


class Clipboard:
  def __init__(self):
    platforms = {
      'nt': self.__winclipboard,
      'posix': self.__linuxclipboard,
      'darwin': self.__macosclipboard
    }
    
    self.set_clipboard = platforms[os.name]
  
  # takes data in bytes
  def __winclipboard(self, data):
    # imports for windows
    import ctypes
    import ctypes.wintypes
    if type(data) != type(b''): # make sure data contains only bytes
      tk.messagebox.showerror(title='Wrong data', message=f'Need to be passed bytes for clipboard, not type {type(data)}')
    
    # start constants for Windows clipboard API
    GMEM_MOVEABLE = 0x0002
    # end constants
    
    # start win32 function definitions
    GlobalAlloc = ctypes.windll.kernel32.GlobalAlloc
    GlobalAlloc.restype = ctypes.wintypes.HGLOBAL
    
    GlobalLock = ctypes.windll.kernel32.GlobalLock
    GlobalLock.argtypes = [ctypes.wintypes.HGLOBAL]
    GlobalLock.restype = ctypes.c_void_p

    GlobalUnlock = ctypes.windll.kernel32.GlobalUnlock
    GlobalUnlock.argtypes = [ctypes.wintypes.HGLOBAL]
    
    OpenClipboard = ctypes.windll.user32.OpenClipboard
    CloseClipboard = ctypes.windll.user32.CloseClipboard
    SetClipboardData = ctypes.windll.user32.SetClipboardData
    SetClipboardData.argtypes = [ctypes.wintypes.UINT, ctypes.wintypes.HANDLE]
    
    memcpy = ctypes.cdll.msvcrt.memcpy
    memcpy.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
    
    EmptyClipboard = ctypes.windll.user32.EmptyClipboard
    # end win32 functions
    
    # start clipboard copy code
    data_char_pointer = ctypes.c_char_p(data) # convert data to a C char*
    d_len = len(data)+1 # get the length of the data for copying later
    
    # copy to private heap
    hMem = GlobalAlloc(GMEM_MOVEABLE, d_len)
    # copy the data input into the heap
    # global_lock returns a void* for memcpy
    memcpy(GlobalLock(hMem), data_char_pointer, d_len)
    GlobalUnlock(hMem) # unlock the heap for the clipboard
    
    # open clipboard, None means current app
    OpenClipboard(None)
    EmptyClipboard() # this is needed for unknown reasons, the docs say this should lose the handle
    SetClipboardData(1, hMem) # set the data to the heap pointer
    CloseClipboard() # close the clipboard handle
    
    # end clipboard copy code
  
  def __linuxclipboard(self):
    tk.messagebox.showerror(title='OS Unsupported', message='Linux is not yet supported for clipboard copy')
  
  def __macosclipboard(self):
    tk.messagebox.showerror(title='OS Unsupported', message='MacOS is not yet supported for clipboard copy')


clip = Clipboard()

clip.set_clipboard(b"Hello")