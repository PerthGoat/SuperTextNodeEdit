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
SuperText runs on Windows and macOS with Python 3, Tk, and Pillow. On macOS it
uses the native AppKit pasteboard (through the built-in JavaScript for
Automation runtime), so no PyObjC package is required. Rich text, plain text,
HTML tables, images, and Finder file copies are exchanged in their native
macOS clipboard formats. Linux can run the editor, but its rich clipboard
integration is not implemented yet.

Keyboard shortcuts use **Ctrl** on Windows/Linux and **Command** on macOS.
Right-click menus also support the standard macOS **Control-click** gesture.

## Creating notes

Use **Nodes → Add Root Node** to create a note at the top level of the node
tree, even when another note is selected. Use **Nodes → Add Child** or
right-click a note and choose **Add Child** to create a note beneath it.

## Ordering notes

Select a note and use **Nodes → Move Up** or **Nodes → Move Down** to
change its position among notes under the same parent. The same commands are
available by right-clicking a note. You can also press **Alt+Up/Down** on
Windows and Linux, or **Option+Up/Down** on macOS.

Manual order is saved per parent in the existing `rtfjournal.ini` file under
the optional `[note_order]` section. Notes that have not been ordered yet are
shown alphabetically, so older config files continue to work without a
migration.

## Searching notes
Use **Edit → Search All Notes** or press **Ctrl+Shift+F** (**Command+Shift+F**
on macOS) to search for a
case-insensitive substring across every saved note. Double-click a result to
open it, including notes in tree branches that have not been expanded yet.

Search uses an incremental SQLite n-gram index, so unchanged RTF files are not
reparsed on every search. The hidden `.supertext-search.sqlite3` file beside the
notes is only a rebuildable cache: it stores paths, file signatures, and hashed
n-grams rather than a second plaintext copy of note contents.

## Hyperlinks

Highlight text and choose **Insert → Hyperlink...** or press **Ctrl+K**
(**Command+K** on macOS). A link
can open another node in the current notebook, a website or other registered
URL, or a file URL. Hyperlinks are saved with the note and preserved by rich
text copy and paste. Right-click a hyperlink to copy its destination or edit
the link.

## Special characters

Choose **Insert → Special Character...** to open a character picker. Symbols
are grouped into categories including checkmarks, arrows, mathematical and
currency symbols, Latin-1, and extended ASCII (CP437). Select a character and
choose **Insert**, or double-click it, to add it at the text cursor.

## Horizontal lines

Choose **Insert → Horizontal Line** to add a divider at the text cursor. The
divider is placed on its own line, spans the full usable document width, and
automatically resizes with the editor. Horizontal lines are preserved when a
note is saved and reopened.

## Format painter

Place the text cursor in formatted text and choose **Format → Format Painter**
or press **Ctrl+Shift+C** (**Command+Shift+C** on macOS). The next text you highlight receives the same font,
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
tab without creating another tab. Selecting notes with the tree's arrow keys
uses the same preview tab; the remaining tabs stay pinned to their notes. Every
double-click creates a separate tab, even when that note is already open. Each
tab keeps its own unsaved edits and undo history.

Use **Ctrl+W** and **Ctrl+Shift+S** (or **Command+W** and **Command+Shift+S** on
macOS) to close the current tab and save all modified tabs. Tabs can also be
closed from their right-click menu (or with the middle mouse button on
Windows/Linux). A leading `*` on a tab means that it has unsaved changes.

## What is required to run this?
You can run this as long as you have Python 3 with Tk and Pillow. Pillow is used because it makes it very easy to convert images to the TK format, grab the clipboard, and ensure that the images in the document are
consitent in their formatting. I like them to all be PNG because I like PNG.

## Tests
Run the full unit test suite with:
```shell
python3 -m unittest discover -s unittests -p "test*.py"
```

The suite covers parser behavior, helper functions, core node/file workflows, RTF text conversion, Tk layout checks, and a visual screenshot smoke test. The screenshot test saves artifacts under `unittests/artifacts/visual/` when the active desktop allows screen capture; it skips cleanly in headless or restricted environments.

## Limitations?
Currently, this program can only handle a limited subset of RTF. This may never change. This means that if someone modified one of your docs and sent it back to you, there's
no guarantee it would work in this program.

In addition, the rich text is currently limited to 1 font per the document. This will probably change in the future as the program gets more fleshed out with more components.
