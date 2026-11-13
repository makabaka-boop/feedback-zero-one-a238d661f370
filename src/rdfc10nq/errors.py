"""Errors raised by the strict N-Quads parser.

Line numbers always count physical lines from 1 based on the LF (U+000A)
characters of the original input byte stream, as required by the task.
"""


class NQuadsParseError(ValueError):
    """A fatal, whole-document N-Quads syntax or encoding violation.

    The whole input is rejected: no partial output is produced and any
    previously existing output file is left untouched.
    """

    def __init__(self, message, line):
        self.message = message
        self.line = int(line)
        super().__init__("line %d: %s" % (self.line, message))
