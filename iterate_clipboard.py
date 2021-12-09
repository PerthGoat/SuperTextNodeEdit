import ctypes
import ctypes.wintypes

EnumClipboardFormats = ctypes.windll.user32.EnumClipboardFormats
EnumClipboardFormats.argtypes = [ctypes.wintypes.UINT]
EnumClipboardFormats.restype = ctypes.wintypes.UINT

RegisterClipboardFormatA = ctypes.windll.user32.RegisterClipboardFormatA
RegisterClipboardFormatA.argtypes = [ctypes.c_char_p]
RegisterClipboardFormatA.restype = ctypes.wintypes.UINT

GetClipboardFormatNameA = ctypes.windll.user32.GetClipboardFormatNameA
GetClipboardFormatNameA.argtypes = [ctypes.wintypes.UINT, ctypes.c_char_p, ctypes.c_int]
GetClipboardFormatNameA.restype = ctypes.c_int

OpenClipboard = ctypes.windll.user32.OpenClipboard
CloseClipboard = ctypes.windll.user32.CloseClipboard

GlobalAlloc = ctypes.windll.kernel32.GlobalAlloc
GlobalAlloc.restype = ctypes.wintypes.HGLOBAL

GlobalFree = ctypes.windll.kernel32.GlobalFree
GlobalFree.argtypes = [ctypes.wintypes.HGLOBAL]

#

'''hMem = GlobalAlloc(0x0002, 1024)

#print(ctypes.c_char_p(clipboard_format_pointer))

fmt = EnumClipboardFormats(0)
#print(fmt)
fmt = EnumClipboardFormats(fmt)
#fmt = 1
#print(fmt)
'''

OpenClipboard(None)

#fmt = EnumClipboardFormats(0)

#charp = ctypes.c_char_p(bytes(1024))

#clipboard_format_pointer = ctypes.create_string_buffer(1024)
'''
while(fmt != 0):
  if GetClipboardFormatNameA(ctypes.wintypes.UINT(fmt), clipboard_format_pointer, ctypes.c_int(256)):
    print(fmt, clipboard_format_pointer.value)
  else:
    pass
  fmt = EnumClipboardFormats(fmt)
  #print(fmt)
'''

#print(clipboard_format_pointer.raw)

#print(fmt)

rich_format = ctypes.c_char_p(b'RTF in UTF8')

rich_format_id = RegisterClipboardFormatA(rich_format)

print(rich_format_id)

#print(ctypes.GetLastError())

CloseClipboard()

#GlobalFree(hMem)