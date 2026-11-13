"""Independent acceptance tests for the strict requirements.

These cover behavior that the task mandates but the off-the-shelf reference
implementation does not share (or cannot verify), so they cannot rely on a
differential comparison:

* strict UTF-8 / BOM / illegal Unicode scalar rejection;
* N-Quads 1.1 edition syntax only (no triple-quoted strings, no bare
  predicates, mandatory EOL between statements, comments);
* upper-case language tags rejected, lower-case accepted;
* whole-document failure with a correct LF-based physical line number;
* blank-node labels shared file-wide, duplicate quad de-duplication without
  merging distinct graphs;
* literal lexical values preserved (no numeric/Unicode/IRI normalization);
* canonical line ordering, LF termination, empty-set -> empty string;
* atomic output replacement and old-file preservation on failure;
* JSON object shape (exactly ``canonical`` and ``sha256``).

Run with: python3 -I tests/test_acceptance.py
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                "..", "src")))

from rdfc10nq import (  # noqa: E402
    NQuadsParseError,
    parse_nquads,
    canonicalize,
    canonical_nquads,
    canonical_sha256,
    build_result,
    render_result_json,
    atomic_write,
)
from rdfc10nq.__main__ import run  # noqa: E402


def canon(raw):
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    quads = parse_nquads(raw)
    return canonical_nquads(quads, canonicalize(quads))


class StrictEncodingTest(unittest.TestCase):
    def _rejects(self, raw, needle=None):
        with self.assertRaises(NQuadsParseError) as ctx:
            parse_nquads(raw)
        if needle is not None:
            self.assertIn(needle, str(ctx.exception))
        return ctx.exception.line

    def test_reject_utf8_bom(self):
        line = self._rejects(b"\xef\xbb\xbf<urn:s> <urn:p> <urn:o> .\n")
        self.assertEqual(line, 1)

    def test_uchar_bom_is_valid_data_not_encoding_bom(self):
        # A leading *encoding* BOM is rejected, but U+FEFF reached through a
        # UCHAR escape is an ordinary (if unusual) literal code point and is
        # legal N-Quads data; it serializes back as the native character.
        out = canon(b'<urn:s> <urn:p> "\\uFEFF" .\n')
        self.assertIn("﻿", out)

    def test_reject_invalid_utf8_reports_line(self):
        # The bad byte 0xFF is on the third physical line.
        raw = b'<urn:a> <urn:p> "ok" .\n<urn:b> <urn:p> "ok" .\n\xff\xfe\n'
        line = self._rejects(raw)
        self.assertEqual(line, 3)

    def test_reject_surrogate_escape(self):
        self._rejects(b'<urn:s> <urn:p> "\\uD800" .\n')
        self._rejects(b'<urn:s> <urn:p> "\\U0000DFFF" .\n')

    def test_reject_overlong_utf8(self):
        # Overlong encoding of '/': 0xC0 0xAF is invalid UTF-8.
        self._rejects(b"<urn:x>\xc0\xaf <urn:p> <urn:o> .\n")

    def test_accepts_multibyte_and_astral(self):
        out = canon('<urn:s> <urn:p> "中\U0001F303" .\n')
        self.assertIn('"中\U0001F303"', out)


class StrictSyntaxTest(unittest.TestCase):
    def _rejects(self, text):
        with self.assertRaises(NQuadsParseError):
            parse_nquads(text.encode("utf-8"))

    def test_lowercase_language_accepted(self):
        out = canon('<urn:s> <urn:p> "x"@en-gb .\n')
        self.assertIn('"x"@en-gb', out)

    def test_uppercase_language_rejected(self):
        with self.assertRaises(NQuadsParseError) as ctx:
            parse_nquads(b'<urn:s> <urn:p> "x"@EN .\n')
        self.assertEqual(ctx.exception.line, 1)
        with self.assertRaises(NQuadsParseError):
            parse_nquads(b'<urn:s> <urn:p> "x"@en-GB .\n')

    def test_comment_lines_accepted(self):
        text = (
            "# header comment\n"
            "<urn:s> <urn:p> <urn:o> . # trailing comment\n"
            "# another\n"
        )
        out = canon(text)
        self.assertEqual(out, "<urn:s> <urn:p> <urn:o> .\n")

    def test_statements_must_end_with_eol(self):
        # Two statements on one physical line is not N-Quads 1.1.
        self._rejects('<urn:a> <urn:p> <urn:b> . <urn:c> <urn:p> <urn:d> .\n')

    def test_no_triple_quoted_strings(self):
        self._rejects('<urn:s> <urn:p> """x""" .\n')

    def test_unescaped_newline_in_literal_rejected(self):
        self._rejects('<urn:s> <urn:p> "a\nb" .\n')

    def test_bad_echar_rejected(self):
        self._rejects('<urn:s> <urn:p> "a\\q" .\n')

    def test_malformed_uchar_rejected(self):
        self._rejects('<urn:s> <urn:p> "\\u12" .\n')
        self._rejects('<urn:s> <urn:p> "\\U0012" .\n')

    def test_illegal_iriref_char_rejected(self):
        self._rejects('<urn:s p> <urn:p> <urn:o> .\n')
        self._rejects('<urn:s> <urn:p> <urn:o|x> .\n')

    def test_bnode_label_grammar(self):
        # A trailing dot belongs to statement syntax, not the label.
        out = canon('_:a.b <urn:p> _:c .\n')
        self.assertIn("_:c14n", out)
        self._rejects('_: <urn:p> <urn:o> .\n')

    def test_blank_line_and_crlf(self):
        out = canon("<urn:s> <urn:p> <urn:o> .\r\n\r\n")
        self.assertEqual(out, "<urn:s> <urn:p> <urn:o> .\n")

    def test_error_line_number_counts_lf(self):
        text = (
            "<urn:a> <urn:p> <urn:o> .\n"
            "<urn:b> <urn:p> <urn:o> .\n"
            "<urn:c> <urn:p> \"bad\\q\" .\n"
        )
        with self.assertRaises(NQuadsParseError) as ctx:
            parse_nquads(text.encode("utf-8"))
        self.assertEqual(ctx.exception.line, 3)


class DatasetSemanticsTest(unittest.TestCase):
    def test_bnode_label_shared_file_wide(self):
        # The same label in two quads denotes one blank node.
        out = canon('_:a <urn:p> "1" .\n_:a <urn:q> "2" .\n')
        labels = {t for t in out.split() if t.startswith("_:c14n")}
        self.assertEqual(len(labels), 1)

    def test_duplicate_quads_deduped(self):
        text = '<urn:s> <urn:p> <urn:o> .\n<urn:s> <urn:p> <urn:o> .\n'
        self.assertEqual(canon(text), "<urn:s> <urn:p> <urn:o> .\n")

    def test_graphs_are_not_merged(self):
        # Same triple in default vs named graph must survive as two quads.
        text = (
            "<urn:s> <urn:p> <urn:o> .\n"
            "<urn:s> <urn:p> <urn:o> <urn:g> .\n"
        )
        out = canon(text)
        self.assertEqual(out.count("\n"), 2)
        self.assertIn("<urn:g> .\n", out)

    def test_blank_node_named_graph(self):
        out = canon("_:a <urn:p> <urn:o> _:g .\n")
        # Both blank nodes must receive canonical labels.
        self.assertEqual(out.count("_:c14n"), 2)

    def test_literal_lexical_value_preserved(self):
        # "01" and "1" are distinct lexical forms even for xsd:integer.
        text = (
            '<urn:s> <urn:p> "01"^^<http://www.w3.org/2001/XMLSchema#integer> .\n'
            '<urn:s> <urn:q> "1"^^<http://www.w3.org/2001/XMLSchema#integer> .\n'
        )
        out = canon(text)
        self.assertEqual(out.count("\n"), 2)
        self.assertIn('"01"^^', out)
        self.assertIn('"1"^^', out)

    def test_xsd_string_datatype_suppressed(self):
        out = canon(
            '<urn:s> <urn:p> "x"^^<http://www.w3.org/2001/XMLSchema#string> .\n'
        )
        self.assertEqual(out, '<urn:s> <urn:p> "x" .\n')

    def test_no_unicode_or_iri_normalization(self):
        # A UCHAR-escaped space decodes to a space inside the IRI value; no
        # IRI normalization is performed.  On serialization the space cannot
        # appear raw inside IRIREF, so canonical N-Quads re-emits it as the
        # UCHAR escape (value unchanged, only canonical escaping applied).
        out = canon('<urn:s\\u0020x> <urn:p> <urn:o> .\n')
        self.assertIn("<urn:s\\u0020x>", out)


class CanonicalFormTest(unittest.TestCase):
    def test_spec_example(self):
        out = canon('_:a <urn:p> "x" .\n')
        self.assertEqual(out, '_:c14n0 <urn:p> "x" .\n')

    def test_lines_sorted_and_lf_terminated(self):
        text = (
            "<urn:z> <urn:p> <urn:o> .\n"
            "<urn:a> <urn:p> <urn:o> .\n"
        )
        out = canon(text)
        lines = out.split("\n")
        self.assertEqual(lines[-1], "")  # final LF
        body = lines[:-1]
        self.assertEqual(body, sorted(body))

    def test_empty_dataset(self):
        self.assertEqual(canon(""), "")
        self.assertEqual(canon("\n\n"), "")

    def test_sha256_matches_utf8_bytes(self):
        text = '_:a <urn:p> "x" .\n'
        result = build_result(parse_nquads(text.encode()),
                              canonicalize(parse_nquads(text.encode())))
        self.assertEqual(
            result["sha256"],
            hashlib.sha256(result["canonical"].encode("utf-8")).hexdigest())
        self.assertRegex(result["sha256"], r"^[0-9a-f]{64}$")

    def test_json_object_has_exactly_two_string_fields(self):
        text = '<urn:s> <urn:p> <urn:o> .\n'
        quads = parse_nquads(text.encode())
        payload = render_result_json(build_result(quads, canonicalize(quads)))
        obj = json.loads(payload)
        self.assertEqual(set(obj.keys()), {"canonical", "sha256"})
        self.assertIsInstance(obj["canonical"], str)
        self.assertIsInstance(obj["sha256"], str)

    def test_uchar_escaping_of_control_chars(self):
        # U+000B (VT) must be a lowercase-marker, uppercase-hex UCHAR.
        out = canon(b'<urn:s> <urn:p> "\\u000B" .\n')
        self.assertIn("\\u000B", out)
        # A raw VT code point inside the literal is illegal input (controls
        # below U+0020 must be escaped in STRING_LITERAL_QUOTE).
        with self.assertRaises(NQuadsParseError):
            canon('<urn:s> <urn:p> "\u000b" .\n')
        # C1 control U+0085 is a valid XML 1.1 Char -> native code point.
        out2 = canon('<urn:s> <urn:p> "\u0085" .\n')
        self.assertIn("\u0085", out2)
        self.assertNotIn("\\u0085", out2)


class OutputReplacementTest(unittest.TestCase):
    def test_atomic_success_replaces_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp = os.path.join(tmp, "in.nq")
            out = os.path.join(tmp, "out.json")
            with open(out, "w", encoding="utf-8") as handle:
                handle.write("OLD CONTENT")
            with open(inp, "w", encoding="utf-8") as handle:
                handle.write('<urn:s> <urn:p> <urn:o> .\n')
            run(inp, out)
            with open(out, encoding="utf-8") as handle:
                written = handle.read()
            obj = json.loads(written)
            self.assertIn("canonical", obj)
            self.assertNotIn("OLD", written)

    def test_failure_keeps_old_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp = os.path.join(tmp, "in.nq")
            out = os.path.join(tmp, "out.json")
            sentinel = "KEEP ME"
            with open(out, "w", encoding="utf-8") as handle:
                handle.write(sentinel)
            # Invalid syntax on line 2.
            with open(inp, "w", encoding="utf-8") as handle:
                handle.write('<urn:a> <urn:p> <urn:o> .\n'
                             '<urn:b> <urn:p> "bad\\q" .\n')
            with self.assertRaises(NQuadsParseError):
                run(inp, out)
            with open(out, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), sentinel)

    def test_atomic_write_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.json")
            atomic_write(path, '{"ok": true}\n')
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), '{"ok": true}\n')


if __name__ == "__main__":
    unittest.main(verbosity=2)
