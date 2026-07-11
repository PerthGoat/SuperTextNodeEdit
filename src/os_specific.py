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
    FILES = 15 # CF_HDROP
    RTF=0x99
    RTF_NO_OBJ=49514
    def __init__(self):
        platforms = {
            'nt': [self.__winclipboard, self.__winopenclipboard, self.__wincloseclipboard, self.__wingetclipboard, self.__winclearclipboard, lambda : [(lambda : globals().update({'ctypes': importlib.import_module('ctypes')}))(), (lambda : globals().update({'ctypes.wintypes': importlib.import_module('ctypes.wintypes')}))()]],
            'posix': [self.__linuxclipboard, self.__noopclipboard, self.__noopclipboard, self.__unsupportedgetclipboard, self.__noopclipboard, lambda : None],
            'darwin': [self.__macosclipboard, self.__noopclipboard, self.__noopclipboard, self.__unsupportedgetclipboard, self.__noopclipboard, lambda : None]
        }
        #print(globals)
        platform_specific = platforms[os.name]
        
        self.set_clipboard = platform_specific[0]
        self.open_clipboard = platform_specific[1]
        self.close_clipboard = platform_specific[2]
        self.get_clipboard = platform_specific[3]
        self.get_file_paths = self.__wingetfilepaths if os.name == 'nt' else lambda: []
        self.register_format = self.__winregisterformat if os.name == 'nt' else lambda _name: None
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

    def __winregisterformat(self, name):
        """Return the process-local ID for a named clipboard format."""
        RegisterClipboardFormatW = ctypes.windll.user32.RegisterClipboardFormatW
        RegisterClipboardFormatW.argtypes = [ctypes.wintypes.LPCWSTR]
        RegisterClipboardFormatW.restype = ctypes.wintypes.UINT
        format_id = RegisterClipboardFormatW(name)
        if not format_id:
            raise ctypes.WinError()
        return format_id

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
        SetClipboardData.restype = ctypes.wintypes.HANDLE
        
        RegisterClipboardFormatA = ctypes.windll.user32.RegisterClipboardFormatA
        RegisterClipboardFormatA.argtypes = [ctypes.c_char_p]
        RegisterClipboardFormatA.restype = ctypes.wintypes.UINT
        
        memcpy = ctypes.cdll.msvcrt.memcpy
        memcpy.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
        
        # end win32 functions
        
        # open clipboard, None means current app
        #OpenClipboard(None)
        #EmptyClipboard() # this is needed for unknown reasons, the docs say this should lose the handle

        def set_clipboard_data(data_type_id, payload):
            d_len = len(payload)
            if data_type_id == self.UNITEXT:
                d_len += 2
            elif data_type_id == self.FILES:
                pass
            else:
                d_len += 1
            data_buffer = ctypes.create_string_buffer(payload, d_len)

            # SetClipboardData takes ownership of the handle on success.
            hMem = GlobalAlloc(GMEM_MOVEABLE, d_len)
            if not hMem:
                raise ctypes.WinError()

            data_lock = GlobalLock(hMem)
            if not data_lock:
                GlobalFree(hMem)
                raise ctypes.WinError()

            memcpy(data_lock, data_buffer, d_len)
            GlobalUnlock(hMem) # unlock the heap for the clipboard

            if not SetClipboardData(data_type_id, hMem):
                GlobalFree(hMem)
                raise ctypes.WinError()

        if data_type == self.RTF_NO_OBJ:
            # set up RTF format
            rich_format_noobj = ctypes.c_char_p(b'Rich Text Format Without Objects')
            rich_format_id_noobj = RegisterClipboardFormatA(rich_format_noobj)
            rich_format_obj = ctypes.c_char_p(b'Rich Text Format')
            rich_format_id_obj = RegisterClipboardFormatA(rich_format_obj)
            set_clipboard_data(rich_format_id_noobj, data) # RTF
            set_clipboard_data(rich_format_id_obj, data) # RTF
        else:
            set_clipboard_data(data_type, data) # Non-RTF
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
            #print('No Rich Text On Clipboard To Paste!')
            return None
        res = GetClipboardData(clipformats['Rich Text Format Without Objects'])

        data_lock = GlobalLock(res)
        text = ctypes.c_char_p(data_lock)
        val = text.value.decode('ascii')
        GlobalUnlock(data_lock)

        return val

    def __wingetfilepaths(self):
        """Return files copied by Explorer without reading their contents."""
        GetClipboardData = ctypes.windll.user32.GetClipboardData
        GetClipboardData.argtypes = [ctypes.wintypes.UINT]
        GetClipboardData.restype = ctypes.wintypes.HANDLE
        DragQueryFileW = ctypes.windll.shell32.DragQueryFileW
        DragQueryFileW.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.UINT,
                                   ctypes.wintypes.LPWSTR, ctypes.wintypes.UINT]
        DragQueryFileW.restype = ctypes.wintypes.UINT

        drop_handle = GetClipboardData(self.FILES)
        if not drop_handle:
            return []
        count = DragQueryFileW(drop_handle, 0xFFFFFFFF, None, 0)
        paths = []
        for index in range(count):
            length = DragQueryFileW(drop_handle, index, None, 0)
            buffer = ctypes.create_unicode_buffer(length + 1)
            DragQueryFileW(drop_handle, index, buffer, length + 1)
            paths.append(buffer.value)
        return paths


    def __linuxclipboard(self):
        tk.messagebox.showerror(title='OS Unsupported', message='Linux is not yet supported for clipboard copy')
    
    def __macosclipboard(self):
        tk.messagebox.showerror(title='OS Unsupported', message='MacOS is not yet supported for clipboard copy')

    def __noopclipboard(self):
        pass

    def __unsupportedgetclipboard(self):
        return None

'''im = Image.open(r"")
ibytes = io.BytesIO()
im.save(ibytes, 'DIB')

by = ibytes.getvalue()
clip = Clipboard()

clip.set_clipboard(by, clip.BITMAP)'''
