# RTF parsing
from src.RTFParser import RTFParseError, RTFParser

import random
import string
import unittest

class TestRTFParsing(unittest.TestCase):
    def assert_token_tree_shape(self, tokens):
        for token in tokens:
            if isinstance(token, list):
                self.assert_token_tree_shape(token)
                continue

            self.assertIsInstance(token, tuple)
            self.assertEqual(2, len(token))
            self.assertIn(token[0], {"TEXT", "CMDPARAM", "RTFCMD"})
            self.assertIsInstance(token[1], str)

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

    def random_valid_rtf(self, rng, max_depth=3):
        commands = ["rtf1", "ansi", "pard", "par", "b", "i", "fs22", "f0"]
        text_chars = string.ascii_letters + string.digits + " .,;:-_"

        def random_text():
            return "".join(rng.choice(text_chars) for _ in range(rng.randint(1, 12)))

        def random_piece(depth):
            choice = rng.randrange(6 if depth < max_depth else 5)
            if choice == 0:
                return "\\" + rng.choice(commands) + rng.choice([" ", "\n", "\t", ""])
            if choice == 1:
                return rng.choice([r"\\", r"\{", r"\}"])
            if choice == 2:
                return rf"\u{rng.randint(0, 0xFFFF)}?"
            if choice == 3:
                return random_text()
            if choice == 4:
                return rng.choice([" ", "\n", "\r", "\t", "\x00"])
            return random_group(depth + 1)

        def random_group(depth):
            return "{" + "".join(random_piece(depth) for _ in range(rng.randint(0, 10))) + "}"

        return random_group(0)

    def test_fuzz_valid_balanced_rtf_shapes(self):
        rng = random.Random(20260703)

        for _ in range(300):
            with self.subTest():
                parsed = RTFParser(self.random_valid_rtf(rng)).parseme()
                self.assertIsInstance(parsed, list)
                self.assert_token_tree_shape(parsed)

    def test_fuzz_arbitrary_input_only_raises_parse_errors(self):
        rng = random.Random(20260704)
        alphabet = string.ascii_letters + string.digits + "{}\\ \t\r\n\x00?;-"

        for _ in range(500):
            data = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 100)))
            with self.subTest(data=data):
                try:
                    parsed = RTFParser(data).parseme()
                except RTFParseError:
                    continue

                self.assertIsInstance(parsed, list)
                self.assert_token_tree_shape(parsed)
