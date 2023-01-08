# RTF parsing
from src.helperfunctions import *

import unittest

class TestHelperFunctions(unittest.TestCase):
    def test_basicrename(self):
        path1 = r'nodes/newNode0/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.rtf'
        path2 = r'nodes\othernode\bb.rtf'

        newpath = RenamePathToPath(path1, path2)

        self.assertEqual(os.path.normpath(path2), newpath)
    def test_badrename1(self):
        path1 = r'nodes/newNode0/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.rtf'
        path2 = r'nodes\othernod\bb.rtf'

        self.assertRaises(AssertionError, lambda: RenamePathToPath(path1, path2))
    def test_badrename2(self):
        path1 = r'nodes/newNode0'
        path2 = r'nodes/newNode0/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'

        self.assertRaises(AssertionError, lambda: RenamePathToPath(path1, path2))
    def test_badrename3(self):
        path1 = r'nodes/newNode0'
        path2 = r'newNode0/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'

        self.assertRaises(AssertionError, lambda: RenamePathToPath(path1, path2))