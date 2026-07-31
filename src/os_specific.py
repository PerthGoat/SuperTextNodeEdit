"""Native clipboard integration used by SuperText.

Windows exposes its clipboard through Win32.  macOS exposes the equivalent
pasteboard APIs through AppKit; the small JXA bridge below lets us use AppKit
without making PyObjC another application dependency.
"""

import base64
import ctypes
import ctypes.wintypes
import io
import json
import os
import re
import struct
import subprocess
import sys

from PIL import Image


class ClipboardError(RuntimeError):
    """Raised when a native clipboard operation cannot be completed."""


class Clipboard:
    # Win32's standard format IDs are kept as the public API.  The macOS
    # backend translates them to Uniform Type Identifiers before writing.
    TEXT = 1
    UNITEXT = 13
    BITMAP = 0x8
    FILES = 15
    RTF = 0x99
    RTF_NO_OBJ = 49514

    _MAC_FORMATS = {
        "HTML Format": "public.html",
    }

    _MAC_WRITE_SCRIPT = r"""
ObjC.import('AppKit');
ObjC.import('Foundation');

function run(argv) {
    const input = $.NSFileHandle.fileHandleWithStandardInput.readDataToEndOfFile;
    const string = $.NSString.alloc.initWithDataEncoding(input, $.NSUTF8StringEncoding);
    const payload = JSON.parse(ObjC.unwrap(string));
    const pasteboard = $.NSPasteboard.generalPasteboard;
    if (pasteboard.isNil()) {
        throw new Error('The general pasteboard is unavailable');
    }
    pasteboard.clearContents;

    const urls = $.NSMutableArray.array;
    payload.files.forEach(function (path) {
        urls.addObject($.NSURL.fileURLWithPath($(path)));
    });
    if (urls.count > 0) {
        if (!pasteboard.writeObjects(urls)) {
            throw new Error('Could not write file URLs to the pasteboard');
        }
    }

    payload.items.forEach(function (item) {
        const data = $.NSData.alloc.initWithBase64EncodedStringOptions(
            $(item.data), 0
        );
        if (!pasteboard.setDataForType(data, $(item.type))) {
            throw new Error('Could not write ' + item.type + ' to the pasteboard');
        }
    });
    return '';
}
"""

    _MAC_READ_RTF_SCRIPT = r"""
ObjC.import('AppKit');
ObjC.import('Foundation');

function run(argv) {
    const pasteboard = $.NSPasteboard.generalPasteboard;
    if (pasteboard.isNil()) {
        return '';
    }
    const data = pasteboard.dataForType($('public.rtf'));
    if (data.isNil()) {
        return '';
    }
    return ObjC.unwrap(data.base64EncodedStringWithOptions(0));
}
"""

    _MAC_READ_FILES_SCRIPT = r"""
ObjC.import('AppKit');
ObjC.import('Foundation');

function run(argv) {
    const pasteboard = $.NSPasteboard.generalPasteboard;
    if (pasteboard.isNil()) {
        return '[]';
    }
    const classes = $.NSArray.arrayWithObject($.NSURL);
    const options = $.NSDictionary.dictionaryWithObjectForKey(
        $.NSNumber.numberWithBool(true),
        $.NSPasteboardURLReadingFileURLsOnlyKey
    );
    const urls = pasteboard.readObjectsForClassesOptions(
        classes, options
    );
    const paths = [];
    if (!urls.isNil()) {
        for (let index = 0; index < urls.count; index++) {
            paths.push(ObjC.unwrap(urls.objectAtIndex(index).path));
        }
    }
    return JSON.stringify(paths);
}
"""

    def __init__(self):
        self._mac_pending_items = None
        self._mac_pending_files = None

        if sys.platform == "darwin":
            self.text_encoding = "utf-8"
            self.set_clipboard = self.__macosclipboard
            self.open_clipboard = self.__macosopenclipboard
            self.close_clipboard = self.__macoscloseclipboard
            self.get_clipboard = self.__macosgetclipboard
            self.get_file_paths = self.__macosgetfilepaths
            self.register_format = self.__macosregisterformat
            self.clear_clipboard = self.__macosclearclipboard
        elif os.name == "nt":
            self.text_encoding = "mbcs"
            self.set_clipboard = self.__winclipboard
            self.open_clipboard = self.__winopenclipboard
            self.close_clipboard = self.__wincloseclipboard
            self.get_clipboard = self.__wingetclipboard
            self.get_file_paths = self.__wingetfilepaths
            self.register_format = self.__winregisterformat
            self.clear_clipboard = self.__winclearclipboard
        else:
            self.text_encoding = "utf-8"
            self.set_clipboard = self.__linuxclipboard
            self.open_clipboard = self.__noopclipboard
            self.close_clipboard = self.__noopclipboard
            self.get_clipboard = self.__unsupportedgetclipboard
            self.get_file_paths = lambda: []
            self.register_format = lambda _name: None
            self.clear_clipboard = self.__noopclipboard

    def encode_text(self, text):
        """Encode plain text for the active native clipboard backend."""
        return text.encode(self.text_encoding)

    def __winopenclipboard(self):
        OpenClipboard = ctypes.windll.user32.OpenClipboard
        OpenClipboard(None)

    def __wincloseclipboard(self):
        CloseClipboard = ctypes.windll.user32.CloseClipboard
        CloseClipboard()

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

    def __winclipboard(self, data, data_type):
        if not isinstance(data, bytes):
            raise TypeError(f"Clipboard data must be bytes, not {type(data)!r}")

        GMEM_MOVEABLE = 0x0002

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

        def set_clipboard_data(data_type_id, payload):
            data_length = len(payload)
            if data_type_id == self.UNITEXT:
                data_length += 2
            elif data_type_id != self.FILES:
                data_length += 1
            data_buffer = ctypes.create_string_buffer(payload, data_length)

            memory = GlobalAlloc(GMEM_MOVEABLE, data_length)
            if not memory:
                raise ctypes.WinError()

            data_lock = GlobalLock(memory)
            if not data_lock:
                GlobalFree(memory)
                raise ctypes.WinError()

            memcpy(data_lock, data_buffer, data_length)
            GlobalUnlock(memory)

            # SetClipboardData takes ownership of the allocation on success.
            if not SetClipboardData(data_type_id, memory):
                GlobalFree(memory)
                raise ctypes.WinError()

        if data_type == self.RTF_NO_OBJ:
            no_objects = RegisterClipboardFormatA(b"Rich Text Format Without Objects")
            with_objects = RegisterClipboardFormatA(b"Rich Text Format")
            set_clipboard_data(no_objects, data)
            set_clipboard_data(with_objects, data)
        else:
            set_clipboard_data(data_type, data)

    def __wingetclipboardformats(self):
        EnumClipboardFormats = ctypes.windll.user32.EnumClipboardFormats
        EnumClipboardFormats.argtypes = [ctypes.wintypes.UINT]
        EnumClipboardFormats.restype = ctypes.wintypes.UINT

        GetClipboardFormatNameA = ctypes.windll.user32.GetClipboardFormatNameA
        GetClipboardFormatNameA.argtypes = [
            ctypes.wintypes.UINT,
            ctypes.wintypes.LPCSTR,
            ctypes.wintypes.INT,
        ]
        GetClipboardFormatNameA.restype = ctypes.wintypes.INT

        data_pointer = ctypes.create_string_buffer(256)
        formats = {}
        next_format = 0
        while True:
            next_format = EnumClipboardFormats(next_format)
            if next_format == 0:
                break
            length = GetClipboardFormatNameA(next_format, data_pointer, 255)
            if length:
                formats[data_pointer.raw[:length].decode("ascii")] = next_format
        return formats

    def __wingetclipboard(self):
        GlobalLock = ctypes.windll.kernel32.GlobalLock
        GlobalLock.argtypes = [ctypes.wintypes.HGLOBAL]
        GlobalLock.restype = ctypes.c_void_p

        GlobalUnlock = ctypes.windll.kernel32.GlobalUnlock
        GlobalUnlock.argtypes = [ctypes.wintypes.HGLOBAL]

        GetClipboardData = ctypes.windll.user32.GetClipboardData
        GetClipboardData.argtypes = [ctypes.wintypes.UINT]
        GetClipboardData.restype = ctypes.wintypes.HANDLE

        formats = self.__wingetclipboardformats()
        format_id = formats.get("Rich Text Format Without Objects")
        if format_id is None:
            format_id = formats.get("Rich Text Format")
        if format_id is None:
            return None

        result = GetClipboardData(format_id)
        data_lock = GlobalLock(result)
        if not data_lock:
            return None
        try:
            value = ctypes.c_char_p(data_lock).value
            return value.decode("ascii") if value is not None else None
        finally:
            GlobalUnlock(result)

    def __wingetfilepaths(self):
        """Return files copied by Explorer without reading their contents."""
        GetClipboardData = ctypes.windll.user32.GetClipboardData
        GetClipboardData.argtypes = [ctypes.wintypes.UINT]
        GetClipboardData.restype = ctypes.wintypes.HANDLE
        DragQueryFileW = ctypes.windll.shell32.DragQueryFileW
        DragQueryFileW.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.UINT,
            ctypes.wintypes.LPWSTR,
            ctypes.wintypes.UINT,
        ]
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

    def __macosopenclipboard(self):
        # AppKit pasteboards do not need locking.  Writes are accumulated so a
        # single clear can advertise plain text, rich text, and HTML together.
        self._mac_pending_items = None
        self._mac_pending_files = None

    def __macosclearclipboard(self):
        self._mac_pending_items = []
        self._mac_pending_files = []

    def __macoscloseclipboard(self):
        if self._mac_pending_items is None:
            return
        payload = {
            "items": [
                {
                    "type": data_type,
                    "data": base64.b64encode(data).decode("ascii"),
                }
                for data_type, data in self._mac_pending_items
            ],
            "files": self._mac_pending_files,
        }
        self.__runosascript(self._MAC_WRITE_SCRIPT, input_data=json.dumps(payload))
        self._mac_pending_items = None
        self._mac_pending_files = None

    def __macosregisterformat(self, name):
        # Windows-only companion formats are unnecessary when NSURL objects
        # are written to NSPasteboard.
        return self._MAC_FORMATS.get(name)

    def __macosclipboard(self, data, data_type):
        if not isinstance(data, bytes):
            raise TypeError(f"Clipboard data must be bytes, not {type(data)!r}")
        if self._mac_pending_items is None:
            # Be forgiving of direct use outside the open/close transaction.
            self.__macosclearclipboard()

        if data_type == self.FILES:
            self._mac_pending_files.extend(self.__filepathsfromdropbytes(data))
            return
        if data_type in (self.RTF, self.RTF_NO_OBJ):
            native_type = "public.rtf"
            native_data = data
        elif data_type == self.UNITEXT:
            native_type = "public.utf8-plain-text"
            native_data = data.decode("utf-16-le").rstrip("\0").encode("utf-8")
        elif data_type == self.TEXT:
            native_type = "public.utf8-plain-text"
            native_data = data
        elif data_type == self.BITMAP:
            native_type = "public.tiff"
            native_data = self.__dibtotiff(data)
        elif data_type == "public.html":
            native_type = data_type
            native_data = self.__htmlfromwindowsclipboard(data)
        elif isinstance(data_type, str):
            native_type = data_type
            native_data = data
        else:
            return

        # A later version of the same UTI should replace, rather than duplicate,
        # the representation already queued for this pasteboard item.
        self._mac_pending_items = [
            item for item in self._mac_pending_items if item[0] != native_type
        ]
        self._mac_pending_items.append((native_type, native_data))

    def __macosgetclipboard(self):
        encoded = self.__runosascript(self._MAC_READ_RTF_SCRIPT).strip()
        if not encoded:
            return None
        data = base64.b64decode(encoded)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("latin-1")

    def __macosgetfilepaths(self):
        output = self.__runosascript(self._MAC_READ_FILES_SCRIPT).strip()
        if not output:
            return []
        paths = json.loads(output)
        return [path for path in paths if isinstance(path, str)]

    @staticmethod
    def __filepathsfromdropbytes(data):
        if len(data) < 20:
            return []
        offset, _, _, _, is_wide = struct.unpack("<IiiII", data[:20])
        if offset < 20 or offset > len(data):
            return []
        encoding = "utf-16-le" if is_wide else "mbcs"
        try:
            names = data[offset:].decode(encoding).rstrip("\0")
        except (LookupError, UnicodeDecodeError):
            return []
        return [name for name in names.split("\0") if name]

    @staticmethod
    def __dibtotiff(data):
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            output = io.BytesIO()
            image.save(output, "TIFF")
        return output.getvalue()

    @staticmethod
    def __htmlfromwindowsclipboard(data):
        match = re.search(br"StartHTML:(\d+).*?EndHTML:(\d+)", data, re.DOTALL)
        if not match:
            return data
        start, end = (int(value) for value in match.groups())
        if 0 <= start <= end <= len(data):
            return data[start:end]
        return data

    @staticmethod
    def __runosascript(script, input_data=None):
        try:
            result = subprocess.run(
                ["/usr/bin/osascript", "-l", "JavaScript", "-e", script],
                input=input_data,
                text=True,
                capture_output=True,
                check=False,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ClipboardError(f"Could not access the macOS pasteboard: {exc}") from exc
        if result.returncode:
            detail = result.stderr.strip() or f"osascript exited {result.returncode}"
            raise ClipboardError(f"Could not access the macOS pasteboard: {detail}")
        return result.stdout

    def __linuxclipboard(self, _data, _data_type):
        raise ClipboardError("Linux native clipboard copy is not yet supported")

    def __noopclipboard(self):
        pass

    def __unsupportedgetclipboard(self):
        return None
