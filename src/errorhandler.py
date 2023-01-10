# error handling + logging for supertext
from enum import Enum
from datetime import datetime
from tkinter import messagebox

class ErrorHandler:
    class LogLevel(Enum):
        Info = 1
        Warn = 2
        Err = 3
    class LogSetting(Enum):
        DEBUG = 1
        RELEASE = 2
    def __init__(self, logsetting : LogSetting, LogFile : str):
        setting = {self.LogSetting.DEBUG: self.__DebugLog, self.LogSetting.RELEASE: self.__ReleaseLog}

        self.myloggingfunc = setting[logsetting]
        self.mylogfile = LogFile

    def ShowError(self, title : str, msg : str):
        messagebox.showerror(title, msg)

    def ShowWarning(self, title : str, msg : str):
        messagebox.showwarning(title, msg)

    def ShowInfo(self, title : str, msg : str):
        messagebox.showinfo(title, msg)

    def Log(self, msg : str, loglvl : LogLevel):
        self.myloggingfunc(msg, loglvl)
    
    def __GeneralLog(self, msg : str, loglvl : LogLevel):
        match loglvl:
            case loglvl.Info:
                print(f'INFO :: {datetime.now().isoformat(" ", "seconds")} >> {msg}')
            case loglvl.Warn:
                print(f'WARN :: {datetime.now().isoformat(" ", "seconds")} >> {msg}')
            case loglvl.Err:
                print(f'ERROR :: {datetime.now().isoformat(" ", "seconds")} >> {msg}')

    def  __DebugLog(self, msg : str, loglvl : LogLevel):
        self.__GeneralLog(msg, loglvl)
        with open(self.mylogfile, 'a') as fi:
            match loglvl:
                case loglvl.Info:
                    fi.write(f'INFO :: {datetime.now().isoformat(" ", "seconds")} >> {msg}\n')
                case loglvl.Warn:
                    fi.write(f'WARN :: {datetime.now().isoformat(" ", "seconds")} >> {msg}\n')
                case loglvl.Err:
                    fi.write(f'ERROR :: {datetime.now().isoformat(" ", "seconds")} >> {msg}\n')
    def __ReleaseLog(self, msg : str, loglvl : LogLevel):
        if loglvl == loglvl.Warn or loglvl == loglvl.Info:
            return None

        self.__GeneralLog(msg, loglvl)
