# RTF parsing
from src.RTFParser import RTFParser

import unittest

class TestRTFParsing(unittest.TestCase):
    def test_basicfile(self):
        testfile_path = 'unittests/files/t2.rtf'
        with open(testfile_path, 'r') as fi:
            rtf_text = fi.read()

        RTFParser(rtf_text).parseme()

    def test_parsefail(self):
        badfile_path = 'unittests/files/badfile.rtf'
        with open(badfile_path, 'r') as fi:
            rtf_text = fi.read()

        RTFParser(rtf_text).parseme()

    def test_clippastefile(self):
        badfile_path = 'unittests/files/debugfile.rtf'
        with open(badfile_path, 'r') as fi:
            rtf_text = fi.read()

        contents = RTFParser(rtf_text).parseme()