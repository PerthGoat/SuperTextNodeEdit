from pprint import pprint


# this class tokenizes .RTF files
class RTFTokenizer:
  # takes in RTF text as a string
  def __init__(self, rtf):
    # split into a list of characters to make it easier to pop/push
    self.rtf = list(rtf) # accessible throughout the class
    
    # holds the tokens
    self.tokens = []
  
  # START PARSING HELPER FUNCTIONS
  
  def EOF(self):
    return len(self.rtf) == 0
  
  def peek(self):
    return self.rtf[0]
  
  def pop(self):
    return self.rtf.pop(0)
  
  def commandword(self):
    fullword = ''
    while self.peek().isalnum():
      fullword += self.pop()
    
    return fullword
  
  def normaltext(self):
    assert self.peek().isalnum()
    
    fulltext = ''
    
    while self.peek() != '\\':
      fulltext += self.pop()
    
    
    return fulltext
  
  # returns the fully expanded parsed object that can be easily accessed
  def parse(self):
    while not self.EOF():
      c = self.peek()
      if c.isalnum(): # normal word
        self.tokens += [('textblock', self.normaltext())]
      else:
        match c:
          case '{': # start of an rtf block
            self.tokens += [('blockstart', '{')]
            self.pop()
          case '}': # end of an rtf block
            self.tokens += [('blockend', '}')]
            self.pop()
          case '\\': # start of an rtf command. rtf commands are alphanumeric
            self.pop()
            if self.peek().isalnum():
              self.tokens += [('command', self.commandword())]
            else: # not a command if it's not alpha numeric though, that's just a text escape
              self.tokens += [('escapedcharacter', self.pop())]
          case ' ': # whitespace
            self.tokens += [('whitespace', self.pop())]
          case '\n': # whitespace
            self.tokens += [('whitespace', self.pop())]
          case ';':
            self.tokens += [('endofstatement', self.pop())]
          case '.':
            self.tokens += [('dot', self.pop())]
          case '(':
            self.tokens += [('openparen', self.pop())]
          case ')':
            self.tokens += [('closedparen', self.pop())]
          case _:
            print("Unknown character '" + c + "'")
            exit(1)
    
    pprint(self.tokens)