from lark import Lark, Visitor, Token, Transformer, Discard
from lark.visitors import Interpreter
from pprint import pprint
import json

# the text to parse
with open('profile_pics.rtf', 'r') as fi:
  rtf_text = fi.read()


rtf_grammar = r'''
start         : block

block    : "{" (NEWLINE | WS_INLINE | wordcomment | commandword | block | ";" | regular_text)* "}"

wordcomment : COMMENT commandword

commandword : "\\" FULLWORD [";" | NEWLINE | WS_INLINE]

regular_text : (["\\\\"] FULLWORD (WS_INLINE | NEWLINE)*)+

FULLWORD : ("_" | LETTER | DIGIT | "." | "(" | ")")+

COMMENT : "\\*"

%import common.WS_INLINE
%import common.NEWLINE
%import common.LETTER
%import common.DIGIT
// %import common.WORD
// %ignore WS_INLINE
'''

'''
class ReadRTFTree(Visitor):
  def commandword(self, tree):
    assert tree.data == 'commandword'
    #print([x for x in tree.children if isinstance(x, Token) and x.type == 'letter'])
    
    #print(tree.children)
    
    #return Discard
  
  def block(self, tree):
    assert tree.data == 'block'
    print(tree.children)
    exit(0)
    if self.doc_text == '':
      self.doc_text = ''.join([x.value for x in tree.children if isinstance(x, Token) and x.type == 'regular_text'])
      print(self.doc_text)
'''

class InterpretRTFTree(Interpreter):
  list_context = []
  nesting_level = 0
  def block(self, tree):
    # save pointer to original list context
    old_context = self.list_context
    # add a new list for this block
    self.list_context.append([])
    self.nesting_level += 1
    # set the list context to this list
    self.list_context = self.list_context[-1]
    self.visit_children(tree)
    # restore the old list context before the block execution
    self.list_context = old_context
    self.nesting_level -= 1
  
  def commandword(self, tree):
    #print()
    self.list_context += [('RTFCMD', tree.children[0].value)]
  
  def regular_text(self, tree):
    if self.nesting_level == 1:
      self.list_context += [('TEXT', ''.join([x.value for x in tree.children]))]
    else:
      self.list_context += [('CMDPARAM', ''.join([x.value for x in tree.children]))]

class TransformRemoveComments(Transformer):
  def wordcomment(self, args):
    return Discard

rtf_parser = Lark(rtf_grammar, parser='lalr', lexer='contextual')

parse_results = rtf_parser.parse(rtf_text)

transformed = TransformRemoveComments().transform(parse_results)

#print(parse_results.pretty())

res = InterpretRTFTree()
res.visit(transformed)

print(json.dumps(res.list_context[0], indent=2))

#with open('outputtest.txt', 'w') as fi:
#  fi.write(rtf_parser.parse(rtf_text).pretty())