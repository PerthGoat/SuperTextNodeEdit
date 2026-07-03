# RTF parsing
from src.RTFParser import RTFParseError, RTFParser

import unittest

class TestRTFParsing(unittest.TestCase):
    def test_basicfile(self):
        testfile_path = 'unittests/files/t2.rtf'
        with open(testfile_path, 'r') as fi:
            rtf_text = fi.read()

        self.assertEqual(
            [
                ("RTFCMD", "rtf1"),
                ("RTFCMD", "ansi"),
                ("RTFCMD", "pard"),
                [
                    ("RTFCMD", "fonttbl"),
                    ("RTFCMD", "f0"),
                    ("RTFCMD", "fswiss"),
                    ("CMDPARAM", "Consolas;"),
                ],
                ("RTFCMD", "f0"),
                ("TEXT", "sd"),
            ],
            RTFParser(rtf_text).parseme(),
        )

    def test_parsefail(self):
        badfile_path = 'unittests/files/badfile.rtf'
        with open(badfile_path, 'r') as fi:
            rtf_text = fi.read()

        self.assertRaises(RTFParseError, lambda: RTFParser(rtf_text).parseme())

    def test_clippastefile(self):
        badfile_path = 'unittests/files/debugfile.rtf'
        with open(badfile_path, 'r') as fi:
            rtf_text = fi.read()

        contents = RTFParser(rtf_text).parseme()

        self.assertEqual(("RTFCMD", "rtf1"), contents[0])

    def test_escaped_text_and_unicode(self):
        rtf_text = r"{\rtf1\ansi slash \\ brace \{ close \} snow \u9731?}"

        self.assertEqual(
            [
                ("RTFCMD", "rtf1"),
                ("RTFCMD", "ansi"),
                ("TEXT", "slash"),
                ("TEXT", " "),
                ("TEXT", "\\"),
                ("TEXT", " "),
                ("TEXT", "brace"),
                ("TEXT", " "),
                ("TEXT", "{"),
                ("TEXT", " "),
                ("TEXT", "close"),
                ("TEXT", " "),
                ("TEXT", "}"),
                ("TEXT", " "),
                ("TEXT", "snow"),
                ("TEXT", " "),
                ("TEXT", "\u2603"),
            ],
            RTFParser(rtf_text).parseme(),
        )

    def test_nested_text_is_command_parameter(self):
        rtf_text = r"{\rtf1\ansi{\b bold words} tail}"

        self.assertEqual(
            [
                ("RTFCMD", "rtf1"),
                ("RTFCMD", "ansi"),
                [
                    ("RTFCMD", "b"),
                    ("CMDPARAM", "bold"),
                    ("CMDPARAM", " "),
                    ("CMDPARAM", "words"),
                ],
                ("TEXT", " "),
                ("TEXT", "tail"),
            ],
            RTFParser(rtf_text).parseme(),
        )

    def test_command_consumes_one_whitespace_delimiter(self):
        rtf_text = "{\\rtf1\\ansi line\\par\r\nnext}"

        self.assertEqual(
            [
                ("RTFCMD", "rtf1"),
                ("RTFCMD", "ansi"),
                ("TEXT", "line"),
                ("RTFCMD", "par"),
                ("TEXT", "\n"),
                ("TEXT", "next"),
            ],
            RTFParser(rtf_text).parseme(),
        )

    def test_trailing_non_whitespace_after_root_fails(self):
        self.assertRaises(
            RTFParseError,
            lambda: RTFParser(r"{\rtf1}extra").parseme(),
        )

    def test_missing_root_group_fails(self):
        self.assertRaises(RTFParseError, lambda: RTFParser(r"\rtf1").parseme())
