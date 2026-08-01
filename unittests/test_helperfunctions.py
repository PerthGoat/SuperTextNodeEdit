# RTF parsing
from src.helperfunctions import *

import unittest
import tempfile
from pathlib import Path

class TestHelperFunctions(unittest.TestCase):
    def test_basicrename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path1 = root / 'nodes' / 'newNode0' / 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.rtf'
            path2 = root / 'nodes' / 'othernode' / 'bb.rtf'
            path1.parent.mkdir(parents=True)
            path2.parent.mkdir(parents=True)
            path1.write_text('')

            newpath = RenamePathToPath(path1, path2)

            self.assertEqual(os.path.normpath(path2), newpath)

    def test_goodrename1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path1 = root / 'nodes' / 'newNode0' / 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
            path2 = root / 'nodes' / 'newNode0' / 'aa'
            path1.mkdir(parents=True)
            RenamePathToPath(path1, path2)

    def test_badrename1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path1 = root / 'nodes' / 'newNode0' / 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.rtf'
            path2 = root / 'nodes' / 'othernod' / 'bb.rtf'
            path1.parent.mkdir(parents=True)
            path1.write_text('')

            self.assertRaises(AssertionError, lambda: RenamePathToPath(path1, path2))
    def test_badrename2(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path1 = root / 'nodes' / 'newNode0'
            path2 = root / 'nodes' / 'newNode0' / 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
            path1.mkdir(parents=True)

            self.assertRaises(AssertionError, lambda: RenamePathToPath(path1, path2))
    def test_badrename3(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path1 = root / 'nodes' / 'newNode0'
            path2 = root / 'newNode0' / 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
            path1.mkdir(parents=True)

            self.assertRaises(AssertionError, lambda: RenamePathToPath(path1, path2))
