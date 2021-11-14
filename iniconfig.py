import os

# this class is for handling the .INI config file the application uses to provide some user customization over where the notes are stored etc
class INIConfig:
  def __init__(self, configPath):
    self.configFile = configPath
  
  # parsing helper functions
  
  # looks for newlines or carriage returns
  # searching for both helps multi-platform compatibility
  def linebreak(self, c):
    return c in '\n\r'
  
  # looks for whitespace including spaces, tabs, or linebreaks defined in the linebreak function
  def whitespace(self, c):
    return c == ' ' or c == '\t' or self.linebreak(c)
  
  # looks for square brackets, used in section headers in INI
  def bracket(self, c):
    return c == '[' or c == ']'
  
  # looks for comments, they use semicolons in INI
  def comment(self, c):
    return c == ';'
  
  # looks for an assignment operation, in INI this is only '='
  def operation(self, c):
    return c == '='
  
  # looks for a word, which is not an operation or a linebreak
  def word(self, configStr):
    matchword = ''
    for c in configStr:
      if not self.operation(c) and not self.linebreak(c):
        matchword += c
      else:
        break
    return matchword
  
  # gets a section header, avoiding the trailing square bracket
  def getSectionDef(self, configStr):
    section = ''
    for c in configStr:
      if self.bracket(c):
        break
      section += c
    return section
  
  # reads the .ini config into a dictionary based on the section headers
  def readConfig(self):
    token_dict = {}
    
    # if there is no config file
    if not os.path.isfile(self.configFile): # create one with a sane default header, Consolas monospaced font, and set the text in the paragraph to use this font with f0
      default_rtf_header = r'{\rtf1\ansi\pard {\fonttbl\f0\fswiss Consolas;}\f0 '
      with open(self.configFile, 'w') as fi:
        fi.writelines(['; config file for rtf tree program\n', '[constants]\n', f'RTF_HEADER={default_rtf_header}\n', 'nodeDir=nodes/\n'])
    
    # read in the configFile
    with open(self.configFile, 'r') as fi:
      config = fi.read()
    
    i = 0
    section = '' # hold the current section the program is on
    
    # go through the config file read in
    while i < len(config):
      c = config[i]
      if self.whitespace(c): # if c is whitespace, skip it
        i += 1
      elif self.comment(c): # skip the entire remainder of the line when a comment is encountered
        while not self.linebreak(config[i]):
          i += 1
      elif self.bracket(c): # if there is a bracket there will be a section defininition
        section = self.getSectionDef(config[i+1:]) # skip the starting bracket
        token_dict[section] = {} # create a new token dictionary entry for that section
        i += len(section) + 2 # advance i past the section and brackets
      else: # else section entries are being read in
        w1 = self.word(config[i:]) # this is the variable name
        i += len(w1)
        op = '=' if self.operation(config[i]) else None # operation is equals if it flags as an operation, otherwise it is set to None to enable error checking
        i += 1 # advance past the operation token
        w2 = self.word(config[i:]) # get the assignment value
        i += len(w2)
        
        # assign w1 to w2 for that section
        token_dict[section][w1] = w2
    
    return token_dict
        
        