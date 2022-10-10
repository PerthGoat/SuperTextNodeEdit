from lark import Lark

# the text to parse
with open('testfiles/Test.rtf', 'r') as fi:
  rtf_text = fi.read()


json_grammar = r'''
start         : block

block    : "{" (escaped_letter | string | commandword | block)* "}"

commandword : "\\" (string | (string* ";"))

string : letter*

escaped_letter : "\\{" | "\\}" | "\\\\"

letter : /[a-zA-Z0-9*.()]/

%import common.WS
%ignore WS

'''

json_parser = Lark(json_grammar, parser='earley')

print(json_parser.parse(rtf_text).pretty())