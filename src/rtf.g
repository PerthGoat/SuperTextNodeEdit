// initial start
start: block WS_NOGRAB*

block: BLOCKOPEN (block | command | generictext)* BLOCKCLOSE

command: ESCAPE_SEQUENCE FILLER WS_NOGRAB?

generictext: unicode_char | normaltext

?normaltext: WS_NOGRAB | FILLER | SPECIAL_ESCAPE_CHAR | DOUBLE_ESCAPE

?unicode_char: ESCAPE_SEQUENCE UNICODE_CHAR

UNICODE_CHAR: "u" /[0-9]/+ "?"
FILLER.-1: (/[^{} \t\f\r\n\\]/)+

ESCAPE_SEQUENCE: "\\"

DOUBLE_ESCAPE: ESCAPE_SEQUENCE ESCAPE_SEQUENCE

// special escape char is for weird chars like {} that would be hard to insert into text without escaping them
SPECIAL_ESCAPE_CHAR: ESCAPE_SEQUENCE (BLOCKOPEN | BLOCKCLOSE)

BLOCKOPEN: "{"
BLOCKCLOSE: "}"

// whitespace that doesn't act greedy
WS_NOGRAB: /[ \t\f\r\n\x00]/

// %import common.WS