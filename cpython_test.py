import ctypes
import ctypes.wintypes


global_alloc = ctypes.windll.kernel32.GlobalAlloc
global_alloc.restype = ctypes.wintypes.HGLOBAL

global_free = ctypes.windll.kernel32.GlobalFree
global_free.argtypes = [ctypes.wintypes.HGLOBAL]

global_handle = ctypes.windll.kernel32.GlobalHandle

global_lock = ctypes.windll.kernel32.GlobalLock
global_lock.argtypes = [ctypes.wintypes.HGLOBAL]
global_lock.restype = ctypes.c_void_p

global_unlock = ctypes.windll.kernel32.GlobalUnlock
global_unlock.argtypes = [ctypes.wintypes.HGLOBAL]

open_clipboard = ctypes.windll.user32.OpenClipboard
empty_clipboard = ctypes.windll.user32.EmptyClipboard
close_clipboard = ctypes.windll.user32.CloseClipboard
set_clipboard_data = ctypes.windll.user32.SetClipboardData
set_clipboard_data.argtypes = [ctypes.wintypes.UINT, ctypes.wintypes.HANDLE]

memcpy = ctypes.cdll.msvcrt.memcpy
memcpy.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]

GMEM_MOVEABLE = 0x0002

output = ctypes.c_char_p(b"Test")
slen = len(b"Test")+1

hMem = global_alloc(GMEM_MOVEABLE, slen)
memcpy(global_lock(hMem), output, slen)
global_unlock(hMem)

open_clipboard(None)
empty_clipboard()
set_clipboard_data(1, hMem)
close_clipboard()
