# TODO: Add Other Operating Systems for this
import os
import tkinter as tk
import importlib
import ctypes
import ctypes.wintypes

from pprint import pprint

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

GlobalLock = ctypes.windll.kernel32.GlobalLock
GlobalLock.argtypes = [ctypes.wintypes.HGLOBAL]
GlobalLock.restype = ctypes.c_void_p

GlobalUnlock = ctypes.windll.kernel32.GlobalUnlock
GlobalUnlock.argtypes = [ctypes.wintypes.HGLOBAL]

#data_char_pointer = ctypes.c_char_p(256)
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
#print(nextFormat)

# get clipboard data

GetClipboardData = ctypes.windll.user32.GetClipboardData
GetClipboardData.argtypes = [ctypes.wintypes.UINT]
GetClipboardData.restype = ctypes.wintypes.HANDLE

goal_item = format_mapping_dict['Rich Text Format Without Objects']

res = GetClipboardData(goal_item)

data_lock = GlobalLock(res)
text = ctypes.c_char_p(data_lock)
val = text.value.decode('ascii')
GlobalUnlock(data_lock)

# end

CloseClipboard = ctypes.windll.user32.CloseClipboard
CloseClipboard() # close the clipboard handle

#pprint(format_mapping_dict)

with open('debugfile.rtf', 'w') as fi:
    fi.write(val)