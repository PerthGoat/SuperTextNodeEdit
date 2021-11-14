# this class is for handling the .INI config file the application uses to provide some user customization over where the notes are stored etc
class INIConfig:
  def __init__(self, configPath):
    self.configFile = configPath
  
  # parsing helper functions
  
  # looks for newlines or carriage returns
  # searching for both helps multi-platform compatibility
  def linebreak(self, c):
    return c in '\n\r'