# SuperTextNodeEdit
An epic text editor written in pure Python + Tkinter, saving via the rich text format.

# Warning:
```This project is still early in development and may have bugs causing data loss, loss of compatibility with old files, and new compatability issues with rich text editors. Back up your RTF files please! I use SuperText as a daily driver for note taking at work but I'm aware it may have and has had unexpected shortcomings.```

## What does this offer?
The design is loosely inspired by MemPad (https://www.horstmuc.de/wmem.htm) and CherryTree.

However, there was one huge limitation with MemPad: it does not support images, or any rich text formatting for that matter. For me, for a note-taking app, that's a killer feature, 
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

## Searching notes
Use **Edit → Search All Notes** or press **Ctrl+Shift+F** to search for a
case-insensitive substring across every saved note. Double-click a result to
open it, including notes in tree branches that have not been expanded yet.

Search uses an incremental SQLite n-gram index, so unchanged RTF files are not
reparsed on every search. The hidden `.supertext-search.sqlite3` file beside the
notes is only a rebuildable cache: it stores paths, file signatures, and hashed
n-grams rather than a second plaintext copy of note contents.

## Hyperlinks

Highlight text and choose **Insert → Hyperlink...** or press **Ctrl+K**. A link
can open another node in the current notebook, a website or other registered
URL, or a file URL. Hyperlinks are saved with the note and preserved by rich
text copy and paste.

## Horizontal lines

Choose **Insert → Horizontal Line** to add a divider at the text cursor. The
divider is placed on its own line, spans the full usable document width, and
automatically resizes with the editor. Horizontal lines are preserved when a
note is saved and reopened.

## Format painter

Place the text cursor in formatted text and choose **Format → Format Painter**
or press **Ctrl+Shift+C**. The next text you highlight receives the same font,
size, color, bold, italic, and alignment styling. The painter applies once and
then switches off; press **Escape** to cancel it without applying.

Tables can be copied in interoperable formats by right-clicking anywhere in a
table and choosing **Copy Table as TSV** or **Copy Table as HTML**. Header
separator rows are omitted; the HTML option also provides a formatted table to
applications that accept HTML clipboard content. The same menu can add a row
below the clicked row, add a column to the right of the clicked cell, or
reformat damaged tab- or pipe-delimited rows back into the normal table
structure.

## Archiving notes

Select a note and use **Nodes → Archive** (or right-click it and choose
**Archive**) to compress that note and its complete child subtree. Archives are
stored as ZIP bundles in the hidden `.supertext-archive` folder inside the
notebook directory; the active copies are removed only after the new bundle
passes an integrity check.

Use **Nodes → Browse Archive...** to list or search the visible text and names
of notes inside the compressed bundles. Select any matching row and choose
**Restore Bundle** to return that archived subtree to its original location.
Restore refuses to overwrite an active note at the same path.

## Working with tabs
Double-clicking a note opens it in an editor tab, so several notes can remain
open at the same time. A single click previews the note in the first (leftmost)
tab without creating another tab; the remaining tabs stay pinned to their
notes. Every double-click creates a separate tab, even when that note is
already open. Each tab keeps its own unsaved edits and undo history.

Use **Ctrl+W** to close the current tab and **Ctrl+Shift+S** to save all modified
tabs. Tabs can also be closed with the middle mouse button or their right-click
menu. A leading `*` on a tab means that it has unsaved changes.

## What is required to run this?
You can run this as long as you have Python + PIL. PIL is used because it makes it very easy to convert images to the TK format, grab the clipboard, and ensure that the images in the document are
consitent in their formatting. I like them to all be PNG because I like PNG.

## Tests
Run the full unit test suite with:
```shell
python -m unittest discover -s unittests -p "test*.py"
```

The suite covers parser behavior, helper functions, core node/file workflows, RTF text conversion, Tk layout checks, and a visual screenshot smoke test. The screenshot test saves artifacts under `unittests/artifacts/visual/` when the active desktop allows screen capture; it skips cleanly in headless or restricted environments.

## Limitations?
Currently, this program can only handle a limited subset of RTF. This may never change. This means that if someone modified one of your docs and sent it back to you, there's
no guarantee it would work in this program.

In addition, the rich text is currently limited to 1 font per the document. This will probably change in the future as the program gets more fleshed out with more components.
