"""Strict RDF 1.1 N-Quads (W3C REC 2014-02-25) parser.

The parser is hand-written directly against the N-Quads / N-Triples EBNF
grammar (productions [1]-[10], [141s]-[162s]).  It deliberately accepts no
superset of that edition of the syntax:

* only STRING_LITERAL_QUOTE literals (no ``'''`` / ``\"\"\"`` forms);
* only single space (U+0020) and tab (U+0009) as intra-statement whitespace;
* EOL is one or more CR/LF characters (production [7]);
* comments are allowed at statement boundaries only;
* language tags must be ASCII and lower case;
* UCHAR escapes must decode to valid scalar Unicode code points (no
  surrogates, nothing beyond U+10FFFF).

The input must be strict UTF-8 with no BOM.  Any violation fails the whole
document with an :class:`NQuadsParseError` carrying a physical line number
counted from 1 over the LF characters of the original byte stream.
"""

from .errors import NQuadsParseError
from .terms import iri, bnode, literal as make_literal, RDF_LANG_STRING

# ---------------------------------------------------------------------------
# Character classes (N-Triples 2014 productions [157s], [158s], [160s])
# ---------------------------------------------------------------------------


def _pn_chars_base(c):
    o = ord(c)
    return (
        0x41 <= o <= 0x5A or          # A-Z
        0x61 <= o <= 0x7A or          # a-z
        0xC0 <= o <= 0xD6 or
        0xD8 <= o <= 0xF6 or
        0xF8 <= o <= 0x2FF or
        0x370 <= o <= 0x37D or
        0x37F <= o <= 0x1FFF or
        o in (0x200C, 0x200D) or
        0x2070 <= o <= 0x218F or
        0x2C00 <= o <= 0x2FEF or
        0x3001 <= o <= 0xD7FF or
        0xF900 <= o <= 0xFDCF or
        0xFDF0 <= o <= 0xFFFD or
        0x10000 <= o <= 0xEFFFF
    )


def _pn_chars_u(c):
    return c == "_" or c == ":" or _pn_chars_base(c)


def _pn_chars(c):
    o = ord(c)
    return (
        _pn_chars_u(c) or
        c == "-" or
        0x30 <= o <= 0x39 or          # 0-9
        o == 0xB7 or
        0x300 <= o <= 0x36F or
        0x203F <= o <= 0x2040
    )


def _hex(c):
    return "0" <= c <= "9" or "A" <= c <= "F" or "a" <= c <= "f"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def parse_nquads(data):
    """Parse strict UTF-8 N-Quads bytes into a set of quad tuples.

    Duplicate quad tuples (identical in every component, graph included) are
    collapsed by the returned ``set``; quads in different graphs are never
    merged because the graph term is part of the tuple.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("parse_nquads expects bytes")
    data = bytes(data)

    # Reject a byte-order mark before any decoding.
    if data.startswith(b"\xef\xbb\xbf"):
        raise NQuadsParseError("UTF-8 BOM is not allowed", 1)

    text = _decode_strict_utf8(data)

    # U+FEFF anywhere (including one produced via a UCHAR escape) is invalid.
    bom_line = _line_of(text, text.find("﻿")) if "﻿" in text else -1
    if bom_line >= 0:
        raise NQuadsParseError("U+FEFF byte order mark is not allowed",
                               bom_line)

    parser = _Parser(text)
    parser.parse_document()
    return parser.quads


def _decode_strict_utf8(data):
    try:
        return data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        # 0x0A cannot occur inside a valid multi-byte UTF-8 sequence, so
        # counting LF bytes up to the bad offset gives the physical line.
        line = data.count(b"\n", 0, exc.start) + 1
        raise NQuadsParseError(
            "input is not valid UTF-8 (%s)" % exc.reason, line)


def _line_of(text, index):
    """Physical line (1-based) of ``index`` counted by LF code points."""
    if index < 0:
        return 1
    return text.count("\n", 0, index) + 1


# ---------------------------------------------------------------------------
# Recursive descent parser
# ---------------------------------------------------------------------------


class _Parser:
    def __init__(self, text):
        self.text = text
        self.n = len(text)
        self.pos = 0
        # Current physical line; advanced whenever an LF is consumed.
        self.line = 1
        self.quads = set()

    def fail(self, message):
        raise NQuadsParseError(message, self.line)

    def eof(self):
        return self.pos >= self.n

    def peek(self, offset=0):
        j = self.pos + offset
        if j >= self.n:
            return ""
        return self.text[j]

    # -- whitespace / comments ---------------------------------------------

    def skip_inline_ws(self):
        """Production WS: one or more space/tab characters."""
        start = self.pos
        while self.peek() in (" ", "\t"):
            self.pos += 1
        if self.pos == start:
            self.fail("expected whitespace between N-Quads terminals")

    def skip_separators(self):
        """Consume separators: WS, comments and EOL sequences."""
        while not self.eof():
            c = self.peek()
            if c in (" ", "\t"):
                self.pos += 1
            elif c == "#":
                # Comment runs to (but excluding) end of line / EOF.
                while not self.eof() and self.peek() not in ("\r", "\n"):
                    self.pos += 1
            elif c in ("\r", "\n"):
                self._consume_eol()
            else:
                break

    def _consume_eol(self):
        # Production [7] EOL ::= [#xD#xA]+
        if self.peek() not in ("\r", "\n"):
            self.fail("expected end of line")
        while self.peek() in ("\r", "\n"):
            if self.peek() == "\n":
                self.line += 1
            self.pos += 1

    def expect_end_of_statement(self):
        """After the terminating '.', allow inline WS and a comment, then
        require EOL or EOF (production nquadsDoc structure)."""
        while self.peek() in (" ", "\t"):
            self.pos += 1
        if self.peek() == "#":
            while not self.eof() and self.peek() not in ("\r", "\n"):
                self.pos += 1
        if self.eof():
            return
        if self.peek() in ("\r", "\n"):
            self._consume_eol()
            return
        self.fail("statements must be separated by an end of line")

    # -- document / statements ---------------------------------------------

    def parse_document(self):
        self.skip_separators()
        while not self.eof():
            self.parse_statement()
            self.expect_end_of_statement()
            self.skip_separators()

    def parse_statement(self):
        subject = self.parse_subject()
        self.skip_inline_ws()
        predicate = self.parse_iri()
        self.skip_inline_ws()
        obj = self.parse_object()
        self.skip_inline_ws()
        if self.peek() == "<" or self.peek() == "_":
            graph = self.parse_graph_label()
            self.skip_inline_ws()
        else:
            graph = None
        if self.peek() != ".":
            self.fail("expected '.' to terminate the statement")
        self.pos += 1
        self.quads.add((subject, predicate, obj, graph))

    def parse_subject(self):
        c = self.peek()
        if c == "<":
            return self.parse_iri()
        if c == "_":
            return self.parse_bnode()
        self.fail("expected IRIREF or BLANK_NODE_LABEL as subject")

    def parse_object(self):
        c = self.peek()
        if c == "<":
            return self.parse_iri()
        if c == "_":
            return self.parse_bnode()
        if c == '"':
            return self.parse_literal()
        self.fail("expected IRIREF, BLANK_NODE_LABEL or literal as object")

    def parse_graph_label(self):
        c = self.peek()
        if c == "<":
            return self.parse_iri()
        if c == "_":
            return self.parse_bnode()
        self.fail("expected IRIREF or BLANK_NODE_LABEL as graph label")

    # -- terminals -----------------------------------------------------------

    def parse_iri(self):
        if self.peek() != "<":
            self.fail("expected IRIREF")
        self.pos += 1
        out = []
        while True:
            if self.eof():
                self.fail("unterminated IRIREF")
            c = self.peek()
            if c == ">":
                self.pos += 1
                return iri("".join(out))
            if c == "\\":
                out.append(self.parse_uchar("IRIREF"))
                continue
            o = ord(c)
            if o <= 0x20 or c in '<>"{}|^`':
                self.fail("illegal character U+%04X in IRIREF" % o)
            out.append(c)
            self.pos += 1

    def parse_bnode(self):
        # Production [141s] BLANK_NODE_LABEL ::=
        #   '_:' (PN_CHARS_U | [0-9]) ((PN_CHARS | '.')* PN_CHARS)?
        if self.text.startswith("_:", self.pos):
            self.pos += 2
        else:
            self.fail("expected BLANK_NODE_LABEL ('_:')")
        label_start = self.pos
        c = self.peek()
        if not c or not (_pn_chars_u(c) or "0" <= c <= "9"):
            self.fail("invalid or empty BLANK_NODE_LABEL")
        self.pos += 1
        while True:
            c = self.peek()
            if not c:
                break
            if c == ".":
                # A trailing dot is part of statement syntax, not the label.
                if not _pn_chars(self.peek(1)):
                    break
                self.pos += 1
                continue
            if _pn_chars(c):
                self.pos += 1
                continue
            break
        label = self.text[label_start:self.pos]
        if not label or label.endswith("."):
            self.fail("malformed BLANK_NODE_LABEL")
        return bnode(label)

    def parse_literal(self):
        lexical = self.parse_string_literal()
        language = None
        datatype = None
        if self.peek() == "@":
            language = self.parse_langtag()
        elif self.text.startswith("^^", self.pos):
            self.pos += 2
            datatype = self.parse_iri()[1]
        if language is not None:
            return make_literal(lexical, language=language,
                                datatype=RDF_LANG_STRING)
        return make_literal(lexical, language=None, datatype=datatype)

    def parse_langtag(self):
        # Production [144s] LANGTAG ::=
        #   '@' [a-zA-Z]+ ('-' [a-zA-Z0-9]+)*
        # Task requirement: upper case ASCII letters are rejected, so only
        # lower case letters are admitted in every letter run.
        line = self.line
        if self.peek() != "@":
            self.fail("expected LANGTAG")
        self.pos += 1

        # Initial run: one or more ASCII lower case letters.
        start = self.pos
        while "a" <= self.peek() <= "z":
            self.pos += 1
        if self.pos == start:
            raise NQuadsParseError(
                "malformed LANGTAG (language tags must be ASCII lower "
                "case)", line)

        # Zero or more ('-' (lower-letter | ASCII-digit)+ subtag runs.
        while self.peek() == "-":
            self.pos += 1
            sub_start = self.pos
            c = self.peek()
            while (("a" <= c <= "z") or ("0" <= c <= "9")):
                self.pos += 1
                c = self.peek()
            if self.pos == sub_start:
                raise NQuadsParseError(
                    "malformed LANGTAG (empty subtag after '-')", line)
        return self.text[start:self.pos]

    def parse_string_literal(self):
        # Production [9] STRING_LITERAL_QUOTE ::=
        #   '"' ([^#x22#x5C#xA#xD] | ECHAR | UCHAR)* '"'
        if self.peek() != '"':
            self.fail("expected STRING_LITERAL_QUOTE")
        self.pos += 1
        out = []
        while True:
            if self.eof():
                self.fail("unterminated string literal")
            c = self.peek()
            if c == '"':
                self.pos += 1
                return "".join(out)
            if c in ("\n", "\r"):
                self.fail("unescaped end of line in string literal")
            if c == "\\":
                nxt = self.peek(1)
                if nxt in ("t", "b", "n", "r", "f", '"', "'", "\\"):
                    out.append(self.parse_echar())
                elif nxt in ("u", "U"):
                    out.append(self.parse_uchar("string literal"))
                else:
                    self.fail("invalid ECHAR escape '\\%s'"
                              % (nxt or "<EOF>"))
                continue
            o = ord(c)
            if o <= 0x1F:
                self.fail("illegal control character U+%04X in string "
                          "literal" % o)
            out.append(c)
            self.pos += 1

    def parse_echar(self):
        # Production [153s] ECHAR ::= '\' [tbnrf"'\]
        line = self.line
        self.pos += 1  # backslash
        c = self.peek()
        if c not in ("t", "b", "n", "r", "f", '"', "'", "\\"):
            raise NQuadsParseError("invalid ECHAR escape", line)
        self.pos += 1
        return {
            "t": "\t", "b": "\b", "n": "\n", "r": "\r", "f": "\f",
            '"': '"', "'": "'", "\\": "\\",
        }[c]

    def parse_uchar(self, context):
        # Production [10] UCHAR ::= '\u' HEX{4} | '\U' HEX{8}
        line = self.line
        if self.peek() != "\\" or self.peek(1) not in ("u", "U"):
            self.fail("expected UCHAR escape in %s" % context)
        marker = self.peek(1)
        length = 4 if marker == "u" else 8
        digits_start = self.pos + 2
        digits = self.text[digits_start:digits_start + length]
        if len(digits) != length or not all(_hex(ch) for ch in digits):
            raise NQuadsParseError(
                "malformed UCHAR escape (expected %d hexadecimal digits)"
                % length, line)
        code = int(digits, 16)
        if code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
            raise NQuadsParseError(
                "UCHAR escape U+%04X is not a valid Unicode scalar value"
                % code, line)
        self.pos = digits_start + length
        return chr(code)
