# RTF parsing
from src.errorhandler import *
import tempfile
import unittest

class TestErrorHandlerFunctions(unittest.TestCase):
    def test_basiclogging(self):
        temp = tempfile.NamedTemporaryFile()
        temp.close()
        filename = temp.name
        eh = ErrorHandler(ErrorHandler.LogSetting.DEBUG, filename)
        eh.Log('Hi', ErrorHandler.LogLevel.Info)
        eh.Log('Hello', ErrorHandler.LogLevel.Warn)
        eh.Log('Hihi', ErrorHandler.LogLevel.Warn)
        print('Reading file..')
        with open(filename, 'r') as fi:
            print(fi.read())
