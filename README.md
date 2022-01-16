# SuperTextNodeEdit
An epic text editor written in pure Python + Tkinter, saving via the rich text format.

# Warning:
```This project is still early in development and may have bugs causing data loss, loss of compatibility with old files, introduced compatability issues with MSWORD wordpad.exe etc, and I don't recommend putting anything important in here (yet), especially if you aren't regularly backing up the RTF files somewhere else.```

## What does this offer?
The design is loosely inspired by MemPad (https://www.horstmuc.de/wmem.htm) and CherryTree

However, there was one huge limitation with MemPad: it does not support images, or any rich text formatting for that matter. For me, that's a killer feature, 
especially when it comes to a node-based editor like this. In addition, MemPad is Windows only.. which sucks for everyone else.

CherryTree supports a lot more in terms of images, rich text, etc, but relies on storing documents in formats that would be tricky for people to figure out, or tricky to open in platform built-in rich text editors.

## Format
I designed this to store its contents in a way that would be friendly towards encryption systems that worked on a per-file basis, because I use this with a per-file encryption container that I use on Google drive for my notes.
Each node consists of a .RTF file and a folder, and the contents of each node are the RTFs in that folder, and their folders as well.

## Why rich text?
The .rtf format might seem odd for a project like this, being that it was designed by Microsoft. I specifically chose it so that it would provide a format that is easy to send to
your coworkers or your boss if they needed a copy of one of your notes from your notebook. In addition, every rich text editor that I know of, including WordPad.exe on Windows PCs
that do not have Microsoft Word, is able to open and display a RTF file. Also a lot of newer formats are a lot more complex than RTF, and I'm making this as a hobby project.

## Cross-platform
Since this uses standard Python bindings, it is naturally cross-platform. This means you can easily use this on Windows, Linux, and MacOS (assuming you have Python and PIL!).

## What is required to run this?
You can run this as long as you have Python + PIL. PIL is used because it makes it very easy to convert images to the TK format, grab the clipboard, and ensure that the images in the document are
consitent in their formatting. I like them to all be PNG because I like PNG.

## Limitations?
Currently, this program can only handle a limited subset of RTF. This may never change. This means that if someone modified one of your docs and sent it back to you, there's
no guarantee it would work in this program.

In addition, the rich text is currently limited to 1 font per the document. This will probably change in the future as the program gets more fleshed out with more components.
