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

from uicomponents import ScrollableText

root = tk.Tk()

st = ScrollableText(root)
st.pack(fill='both', expand=True)

print(st.image_create)

root.mainloop()