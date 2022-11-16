# TODO: Add Other Operating Systems for this
import os
import tkinter as tk
import tkinter.messagebox
import importlib

#from PIL import Image
#import io

class Clipboard:
  TEXT = 1 # normal text
  UNITEXT = 13 # windows clipboard likes this
  BITMAP = 0x8
  RTF=0x99
  RTF_NO_OBJ=49514
  def __init__(self):
    platforms = {
      'nt': [self.__winclipboard, self.__winopenclipboard, self.__wincloseclipboard, self.__wingetclipboard, self.__winclearclipboard, lambda : [(lambda : globals().update({'ctypes': importlib.import_module('ctypes')}))(), (lambda : globals().update({'ctypes.wintypes': importlib.import_module('ctypes.wintypes')}))()]],
      'posix': [self.__linuxclipboard, None, None],
      'darwin': [self.__macosclipboard, None, None]
    }
    #print(globals)
    platform_specific = platforms[os.name]
    
    self.set_clipboard = platform_specific[0]
    self.open_clipboard = platform_specific[1]
    self.close_clipboard = platform_specific[2]
    self.get_clipboard = platform_specific[3]
    self.clear_clipboard = platform_specific[4]
    # do imports
    platform_specific[5]()
  
  def __winopenclipboard(self):
    OpenClipboard = ctypes.windll.user32.OpenClipboard
    OpenClipboard(None)
  
  def __wincloseclipboard(self):
    CloseClipboard = ctypes.windll.user32.CloseClipboard
    CloseClipboard() # close the clipboard handle
  
  def __winclearclipboard(self):
    EmptyClipboard = ctypes.windll.user32.EmptyClipboard
    EmptyClipboard()

  # takes data in bytes
  def __winclipboard(self, data, data_type):
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
    
    GlobalFree = ctypes.windll.kernel32.GlobalFree
    GlobalFree.argtypes = [ctypes.wintypes.HGLOBAL]
    
    SetClipboardData = ctypes.windll.user32.SetClipboardData
    SetClipboardData.argtypes = [ctypes.wintypes.UINT, ctypes.wintypes.HANDLE]
    
    RegisterClipboardFormatA = ctypes.windll.user32.RegisterClipboardFormatA
    RegisterClipboardFormatA.argtypes = [ctypes.c_char_p]
    RegisterClipboardFormatA.restype = ctypes.wintypes.UINT
    
    memcpy = ctypes.cdll.msvcrt.memcpy
    memcpy.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
    
    # end win32 functions
    
    if data_type == self.RTF_NO_OBJ:
    # set up RTF format
      rich_format = ctypes.c_char_p(b'Rich Text Format Without Objects')
      rich_format_id = RegisterClipboardFormatA(rich_format)
      data_type = rich_format_id
    
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
    #OpenClipboard(None)
    #EmptyClipboard() # this is needed for unknown reasons, the docs say this should lose the handle
    SetClipboardData(data_type, hMem) # RTF
    
    GlobalFree(hMem)
    # end clipboard copy code
  
  def __wingetclipboardformats(self):
    EnumClipboardFormats = ctypes.windll.user32.EnumClipboardFormats
    EnumClipboardFormats.argtypes = [ctypes.wintypes.UINT]
    EnumClipboardFormats.restype = ctypes.wintypes.UINT

    GetClipboardFormatNameA = ctypes.windll.user32.GetClipboardFormatNameA
    GetClipboardFormatNameA.argtypes = [ctypes.wintypes.UINT, ctypes.wintypes.LPCSTR, ctypes.wintypes.INT]
    GetClipboardFormatNameA.restype = ctypes.wintypes.INT

    data_char_pointer = ctypes.create_string_buffer(256)

    #print(ctypes.cast(data_char_winpointer, ctypes.c_char_p).value)

    format_mapping_dict = {}

    nextFormat = 0
    while True:
        nextFormat = EnumClipboardFormats(nextFormat)
        if nextFormat == 0:
            break
        GetClipboardFormatNameA(nextFormat, data_char_pointer, 255)
        format_mapping_dict[data_char_pointer.value.decode('ascii')] = nextFormat
    return format_mapping_dict

  def __wingetclipboard(self):
    GlobalAlloc = ctypes.windll.kernel32.GlobalAlloc
    GlobalAlloc.restype = ctypes.wintypes.HGLOBAL

    GlobalFree = ctypes.windll.kernel32.GlobalFree
    GlobalFree.argtypes = [ctypes.wintypes.HGLOBAL]

    GlobalLock = ctypes.windll.kernel32.GlobalLock
    GlobalLock.argtypes = [ctypes.wintypes.HGLOBAL]
    GlobalLock.restype = ctypes.c_void_p

    GlobalUnlock = ctypes.windll.kernel32.GlobalUnlock
    GlobalUnlock.argtypes = [ctypes.wintypes.HGLOBAL]

    GetClipboardData = ctypes.windll.user32.GetClipboardData
    GetClipboardData.argtypes = [ctypes.wintypes.UINT]
    GetClipboardData.restype = ctypes.wintypes.HANDLE

    clipformats = self.__wingetclipboardformats()

    if 'Rich Text Format Without Objects' not in clipformats:
      print('No Rich Text On Clipboard To Paste!')
      return None
    res = GetClipboardData(clipformats['Rich Text Format Without Objects'])

    data_lock = GlobalLock(res)
    text = ctypes.c_char_p(data_lock)
    val = text.value.decode('ascii')
    GlobalUnlock(data_lock)

    return val


  def __linuxclipboard(self):
    tk.messagebox.showerror(title='OS Unsupported', message='Linux is not yet supported for clipboard copy')
  
  def __macosclipboard(self):
    tk.messagebox.showerror(title='OS Unsupported', message='MacOS is not yet supported for clipboard copy')

'''im = Image.open(r"")
ibytes = io.BytesIO()
im.save(ibytes, 'DIB')

by = ibytes.getvalue()
clip = Clipboard()

clip.set_clipboard(by, clip.BITMAP)'''