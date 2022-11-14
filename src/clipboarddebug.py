# TODO: Add Other Operating Systems for this
import os
import tkinter as tk
import importlib
import ctypes
import ctypes.wintypes

OpenClipboard = ctypes.windll.user32.OpenClipboard
EmptyClipboard = ctypes.windll.user32.EmptyClipboard
OpenClipboard(None)
#EmptyClipboard() # this is needed for unknown reasons, the docs say this should lose the handle

# do stuff here

EnumClipboardFormats = ctypes.windll.user32.EnumClipboardFormats
EnumClipboardFormats.argtypes = [ctypes.wintypes.UINT]
EnumClipboardFormats.restype = ctypes.wintypes.UINT

GetClipboardFormatNameA = ctypes.windll.user32.GetClipboardFormatNameA
GetClipboardFormatNameA.argtypes = [ctypes.wintypes.UINT, ctypes.wintypes.LPCSTR, ctypes.wintypes.INT]
GetClipboardFormatNameA.restype = ctypes.wintypes.INT

GlobalAlloc = ctypes.windll.kernel32.GlobalAlloc
GlobalAlloc.restype = ctypes.wintypes.HGLOBAL

GlobalFree = ctypes.windll.kernel32.GlobalFree
GlobalFree.argtypes = [ctypes.wintypes.HGLOBAL]

#data_char_pointer = ctypes.c_char_p(256)
data_char_pointer = ctypes.create_string_buffer(256)

#print(ctypes.cast(data_char_winpointer, ctypes.c_char_p).value)

nextFormat = 0
while True:
    nextFormat = EnumClipboardFormats(nextFormat)
    GetClipboardFormatNameA(nextFormat, data_char_pointer, 255)
    print(data_char_pointer.value)
    if nextFormat == 0:
        break
#print(nextFormat)

# end

CloseClipboard = ctypes.windll.user32.CloseClipboard
CloseClipboard() # close the clipboard handle
