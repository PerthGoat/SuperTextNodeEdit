from lark import Lark
from pprint import pprint
import json

# the text to parse
with open('testfiles/Test.rtf', 'r') as fi:
  rtf_text = fi.read()


rtf_grammar = r'''
start         : block

block    : "{" (NEWLINE | WS_INLINE | string | commandword | block)* "}"

commandword : "\\" string [(WS_INLINE string)+] [";" | NEWLINE]

string : letter*

//escaped_letter : "\\{" | "\\}" | "\\\\"

letter : /[a-zA-Z0-9*.() ]/

%import common.WS_INLINE
%import common.NEWLINE
// %ignore WS_INLINE

'''

rtf_parser = Lark(rtf_grammar, parser='lalr', lexer='contextual')

pprint(rtf_parser.parse(rtf_text))