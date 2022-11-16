from lark import Lark, Visitor, Token, Transformer, Discard
from lark.visitors import Interpreter
from pprint import pprint
import json

# grammar I threw together for RTF
# it works pretty ok
rtf_grammar = r'''
// initial start
start: block WS_NOGRAB*

block: BLOCKOPEN (block | command | generictext)* BLOCKCLOSE

command: "\\" FILLER WS_NOGRAB?

generictext: unicode_char | normaltext

?normaltext: WS_NOGRAB | FILLER

?unicode_char: "\\" UNICODE_CHAR

UNICODE_CHAR: "u" /[0-9]/+ "?"
FILLER.-1: /[^{} \t\f\r\n\\]/+

BLOCKOPEN: "{"
BLOCKCLOSE: "}"

// whitespace that doesn't act greedy
WS_NOGRAB: /[ \t\f\r\n]/

// %import common.WS
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
        
        def command(self, tree):
            self.list_context += [('RTFCMD', tree.children[0].value)]
        
        def generictext(self, tree):
            #print(tree.children)
            if self.nesting_level == 1:
                self.list_context += [('TEXT', ''.join([x.value for x in tree.children]))]
            else:
                self.list_context += [('CMDPARAM', ''.join([x.value for x in tree.children]))]
        
    class TransformFixStuff(Transformer):
        def UNICODE_CHAR(self, args):
            char_val = args
            if char_val[0] == 'u':
                uend = char_val.index('?') # end of unicode char literal in RTF is marked by ?
                unicode_char = chr(int(char_val[1:uend]))
                return Token('UNICODE_CHAR_EVAL', unicode_char)
            
            return Token('UNICODE_CHAR', char_val)

    def parseme(self):
        rtf_parser = Lark(rtf_grammar, parser='lalr', lexer='basic')

        parse_results = rtf_parser.parse(self.rtf_text)

        transformed = self.TransformFixStuff().transform(parse_results)
        
        #print(transformed.pretty())
        
        res = self.InterpretRTFTree()
        res.visit(transformed)

        return res.list_context[0]

#with open(r'Y:\ultranotes\copypastas\doge.rtf', 'r') as fi:
    #data = fi.read()

#print(RTFParser(data).parseme()[0:30])