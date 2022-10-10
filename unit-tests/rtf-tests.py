import unittest
from pprint import pprint
import json
from importlib.machinery import SourceFileLoader
RTFTokenizer = SourceFileLoader('RTFParser', '../RTFParser.py').load_module().RTFTokenizer



class TestRTFMethods(unittest.TestCase):
  def test_parse(self):
    with open('../testfiles/Test.rtf', 'r') as fi:
      rtf_text = fi.read()
    RTFTokenizer(rtf_text).parse()

if __name__ == '__main__':
  unittest.main()