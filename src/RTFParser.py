from lark import Lark, Visitor, Token, Transformer, Discard
from lark.visitors import Interpreter
from pprint import pprint
import json

# grammar I threw together for RTF
# it works pretty ok
rtf_grammar = r'''
start         : block

block    : "{" (NEWLINE | WS_INLINE | wordcomment | commandword | block | ";" | regular_word)* "}" NEWLINE*

commandword : ESCAPE FULLWORD [";" | NEWLINE | WS_INLINE]

wordcomment : COMMENT commandword

regular_word : (escaped_char | FULLWORD) (WS_INLINE | NEWLINE)*

escaped_char : (ESCAPE ESCAPE LETTER | ESCAPE UNICODE_CHAR)

UNICODE_CHAR.1 : "u" DIGIT+ "?"

FULLWORD : ALPHABET+

ALPHABET : "_" | LETTER | DIGIT | "." | "(" | ")" | "-" | ":" | "/" | "?" | "=" | "'" | "\""

COMMENT : ESCAPE "*"

ESCAPE : "\\"

%import common.WS_INLINE
%import common.NEWLINE
%import common.LETTER
%import common.DIGIT
// %import common.WORD
// %ignore WS_INLINE
'''

class RTFParser:
    # read in rtf file
    def __init__(self, rtfdata):
        #with open(rtfpath, 'r') as fi:
        #    self.rtf = fi.read()
        self.rtf_text = rtfdata

    # class that interprets the RTF tree using lark
    class InterpretRTFTree(Interpreter):
        def __init__(self):
            self.list_context = []
            self.nesting_level = 0
        
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
            self.list_context += [('RTFCMD', tree.children[1].value)]
        
        def regular_word(self, tree):
            #print(tree.children)
            if self.nesting_level == 1:
                self.list_context += [('TEXT', ''.join([x.value for x in tree.children]))]
            else:
                self.list_context += [('CMDPARAM', ''.join([x.value for x in tree.children]))]

    class TransformFixStuff(Transformer):
        def wordcomment(self, args):
            return Discard
        def escaped_char(self, args):
            char_val = args[1].value
            if char_val[0] == 'u':
                uend = char_val.index('?') # end of unicode char literal in RTF is marked by ?
                unicode_char = chr(int(char_val[1:uend]))
                args[1].value = unicode_char
                return args[1]
            
            return args[1]

    def parseme(self):
        rtf_parser = Lark(rtf_grammar, parser='lalr', lexer='contextual')

        parse_results = rtf_parser.parse(self.rtf_text)

        transformed = self.TransformFixStuff().transform(parse_results)

        #print(transformed.pretty())

        res = self.InterpretRTFTree()
        res.visit(transformed)

        return res.list_context[0]

#with open('debugout.rtf', 'r') as fi:
#    data = fi.read()

#print(RTFParser(data).parseme())