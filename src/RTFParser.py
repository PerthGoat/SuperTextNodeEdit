class RTFParseError(ValueError):
    pass


class RTFParser:
    WHITESPACE = " \t\f\r\n\x00"

    def __init__(self, rtfdata):
        self.rtf_text = rtfdata

    def parseme(self):
        # RTF documents are one root group. Any non-whitespace after that group
        # is treated as malformed input instead of silently ignored.
        tokens, pos = self._parse_group(0, 1)

        while pos < len(self.rtf_text) and self.rtf_text[pos] in self.WHITESPACE:
            pos += 1

        if pos != len(self.rtf_text):
            self._fail(pos, "unexpected content after root group")

        return tokens

    def _parse_group(self, pos, level):
        if pos >= len(self.rtf_text) or self.rtf_text[pos] != "{":
            self._fail(pos, "expected opening brace")

        pos += 1
        tokens = []

        # A group is a balanced brace block containing nested groups, escaped
        # commands/characters, and plain text spans.
        while pos < len(self.rtf_text):
            char = self.rtf_text[pos]

            if char == "{":
                nested_tokens, pos = self._parse_group(pos, level + 1)
                tokens.append(nested_tokens)
            elif char == "}":
                return tokens, pos + 1
            elif char == "\\":
                token, pos = self._parse_escape(pos, level)
                tokens.append(token)
            else:
                token, pos = self._parse_text(pos, level)
                tokens.append(token)

        self._fail(pos, "missing closing brace")

    def _parse_escape(self, pos, level):
        escaped_pos = pos + 1

        if escaped_pos >= len(self.rtf_text):
            self._fail(pos, "dangling escape")

        escaped = self.rtf_text[escaped_pos]

        # These are literal text escapes in RTF, not commands.
        if escaped in "\\{}":
            return self._text_token(escaped, level), escaped_pos + 1

        # Unicode escapes are the only command-like form this parser evaluates.
        # Everything else remains an RTFCMD token for the UI layer to interpret.
        unicode_token = self._parse_unicode_escape(pos, level)
        if unicode_token is not None:
            return unicode_token

        return self._parse_command(pos)

    def _parse_unicode_escape(self, pos, level):
        value_start = pos + 2
        if self.rtf_text[pos + 1] != "u" or value_start >= len(self.rtf_text):
            return None

        value_end = value_start
        if self.rtf_text[value_end] == "-":
            value_end += 1

        digit_start = value_end
        while value_end < len(self.rtf_text) and self.rtf_text[value_end].isdigit():
            value_end += 1

        if value_end == digit_start:
            return None
        if value_end >= len(self.rtf_text) or self.rtf_text[value_end] != "?":
            return None

        codepoint = int(self.rtf_text[value_start:value_end])
        if codepoint < 0:
            # RTF stores signed 16-bit Unicode values in some producers.
            codepoint += 0x10000

        try:
            char = chr(codepoint)
        except ValueError:
            self._fail(pos, f"invalid unicode escape {codepoint}")

        return self._text_token(char, level), value_end + 1

    def _parse_command(self, pos):
        command_start = pos + 1
        command_end = command_start

        # Commands run until a delimiter. One following whitespace delimiter is
        # consumed, matching the old Lark grammar and existing app behavior.
        while command_end < len(self.rtf_text):
            char = self.rtf_text[command_end]
            if char in "{}\\" or char in self.WHITESPACE:
                break
            command_end += 1

        if command_end == command_start:
            self._fail(pos, "expected command after escape")

        if (
            command_end < len(self.rtf_text)
            and self.rtf_text[command_end] in self.WHITESPACE
        ):
            command_end += 1

        command = self.rtf_text[command_start:command_end].rstrip(self.WHITESPACE)
        return ("RTFCMD", command), command_end

    def _parse_text(self, pos, level):
        if self.rtf_text[pos] in self.WHITESPACE:
            return self._text_token(self.rtf_text[pos], level), pos + 1

        text_end = pos
        while text_end < len(self.rtf_text):
            char = self.rtf_text[text_end]
            if char in "{}\\" or char in self.WHITESPACE:
                break
            text_end += 1

        if text_end == pos:
            self._fail(pos, "expected text")

        return self._text_token(self.rtf_text[pos:text_end], level), text_end

    def _text_token(self, text, level):
        # Root group text is document content. Text inside nested groups is kept
        # as command parameter data, preserving the previous parser contract.
        return ("TEXT" if level == 1 else "CMDPARAM", text)

    def _fail(self, pos, message):
        raise RTFParseError(f"{message} at position {pos}")
