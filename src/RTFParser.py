#from lark import Lark, Visitor, Token, Transformer, Discard
#from lark.visitors import Interpreter
from src.rtf_parser_standalone import Lark_StandAlone, Visitor, Token, Transformer, Discard, Interpreter
from pprint import pprint
import json

# to generate parser:
# python -m lark.tools.standalone rtf.g > rtf_parser_standalone.py

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
            self.list_context += [('RTFCMD', tree.children[1].value)]
        
        def generictext(self, tree):
            #print(tree.children)
            if self.nesting_level == 1:
                self.list_context += [('TEXT', ''.join([x.value for x in tree.children]))]
            else:
                self.list_context += [('CMDPARAM', ''.join([x.value for x in tree.children]))]
        
    class TransformFixStuff(Transformer):
        def unicode_char(self, args):
            char_val = args[1]
            if char_val[0] == 'u':
                uend = char_val.index('?') # end of unicode char literal in RTF is marked by ?
                unicode_char = chr(int(char_val[1:uend]))
                return Token('UNICODE_CHAR_EVAL', unicode_char)
            
            return Token('UNICODE_CHAR', char_val)
        def SPECIAL_ESCAPE_CHAR(self, args):
            return Token('SPECIAL_RESOLVED_CHAR', args.replace('\\', ''))
        def DOUBLE_ESCAPE(self, args):
            return Token('DOUBLE_ESCAPE_RESOLVED', args.replace('\\\\', '\\'))

    def parseme(self):
        rtf_parser = Lark_StandAlone() #Lark(rtf_grammar, parser='lalr', lexer='basic')

        parse_results = rtf_parser.parse(self.rtf_text)

        transformed = self.TransformFixStuff().transform(parse_results)
        
        #print(transformed.pretty())
        
        res = self.InterpretRTFTree()
        res.visit(transformed)

        return res.list_context[0]

#with open(r'Y:\ultranotes\things-to-fulfill-20s.rtf', 'r') as fi:
    #data = fi.read()

#print(RTFParser(data).parseme()[0:30])