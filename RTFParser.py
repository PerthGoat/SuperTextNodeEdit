
# this class parses .RTF files into a usable format
# separating out the backslash commands and brace blocks from actual content

class RTFParser:
  # takes in RTF code as a string
  def __init__(self, rtf):
    self.rtf = rtf # accessible throughout the class
  
  # parsing helper functions
  
  # takes in a char and returns if it is the start of an RTF brace block or not
  def blockstart(self, c):
    return c == '{'
  
  # returns if end of RTF brace block
  def blockend(self, c):
    return c == '}'
  
  # returns if there's a backslash, which would indicate a command token would be starting next
  def tokenstart(self, c):
    return c == '\\'
  
  # returns if c is a space
  def space(self, c):
    return c == ' '
  
  # parses a word from rstr until it hits a tokenstart, space, or blockend
  def getFullWord(self, rstr):
    full = ''
    for c in rstr:
      if self.tokenstart(c) or self.space(c) or self.blockstart(c) or self.blockend(c):
        break
      full += c
    
    return full
  
  # gets a words and spaces, for strings of text that shouldn't be separated up
  def getWordsAndSpaces(self, rstr):
    full = ''
    for c in rstr:
      if self.tokenstart(c) or self.blockstart(c) or self.blockend(c):
        break
      full += c
    
    return full
  
  # returns the fully expanded parsed object that can be easily accessed
  def parse(self):
    return self._parse()[0][0]
  
  # parse function that recursively calls new RTFParser instances to parse all blocks on the RTF file
  def _parse(self):
    rtf_token = []
    i = 0
    
    while i < len(self.rtf):
      c = self.rtf[i] # I do this so advancing i doesn't trigger anything unexpected
      if self.blockstart(c): # '{' start of a block
        i += 1 # first get rid of the leading '{'
        nextParse = RTFParser(self.rtf[i:])._parse() # parse the code inside the block
        rtf_token += [nextParse[0]] # append the parsed block contents to the rtf_token list
        i += nextParse[1] # advance i past the parsed content
      elif self.tokenstart(c): # backslash encountered
        i += 1 # advance past the backslash
        fulltoken = self.getFullWord(self.rtf[i:]) # read in the following word, stopping at a space, block character, or backslash
        i += len(fulltoken) # advance i past the word
        if self.rtf[i] == ' ' or (len(fulltoken) == 0 and (self.tokenstart(self.rtf[i]) or self.blockstart(self.rtf[i]) or self.blockend(self.rtf[i]))): # if a space is encountered, skip it too
          if self.rtf[i] != ' ': # then it is an escaped special character
            fulltoken = self.rtf[i]
          if fulltoken[0] != 'u': # look for unicode escape to not kill spaces following it
            i += 1
        
        if fulltoken[0] == 'u':
          fulltoken = [fulltoken]
        
        rtf_token += [fulltoken] # add the token to the rtf_token list
      elif self.blockend(c): # if '}' blockend encountered
        return (rtf_token, i+1) # return the tokenlist alongside how far to advance i for the caller
      else: # else it is a string of text
        wordstr = self.getWordsAndSpaces(self.rtf[i:])
        i += len(wordstr)
        rtf_token += [wordstr]
    
    return [rtf_token] # returned encapsulated to make concatenation easier