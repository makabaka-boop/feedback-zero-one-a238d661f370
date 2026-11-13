"""Canonical N-Quads serialization (RDFC-1.0 section 5 and appendix A).

The layout is fully determined:

* one single space (U+0020) between subject, predicate, object and the
  optional graph label, and one before the terminating ``.``;
* each statement ends with a single LF and the final statement is also
  terminated;
* HEX digits are upper case;
* ECHAR is used for U+0008, U+0009, U+000A, U+000C, U+000D, U+0022, U+005C;
* UCHAR (lowercase ``u``/``U`` marker, uppercase HEX) is used for the other
  control characters, DEL and code points outside the XML 1.1 ``Char``
  production; every other code point is emitted in its native Unicode form;
* ``xsd:string`` typed literals lose their datatype IRI.

Lines are ordered by Unicode code point comparison of the serialized
strings, which is Python's default ``str`` ordering.
"""

import hashlib
import json
import os
import tempfile

from .terms import IRI, BNODE, LITERAL, XSD_STRING

# ECHAR table (appendix A).
_ECHAR = {
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
    '"': '\\"',
    "\\": "\\\\",
}


def _uchar(code):
    if code <= 0xFFFF:
        return "\\u%04X" % code
    return "\\U%08X" % code


def _is_xml11_char(code):
    """XML 1.1 ``Char`` production (excluding the surrogate block)."""
    return (
        code == 0x9 or
        code == 0xA or
        code == 0xD or
        0x20 <= code <= 0xD7FF or
        0xE000 <= code <= 0xFFFD or
        0x10000 <= code <= 0x10FFFF
    )


def _escape_literal(text):
    out = []
    for ch in text:
        if ch in _ECHAR:
            out.append(_ECHAR[ch])
            continue
        code = ord(ch)
        if (
            code <= 0x1F or
            code == 0x7F or
            not _is_xml11_char(code)
        ):
            # Appendix A: U+0000..U+0007, U+000B, U+000E..U+001F, DEL and
            # non-XML11 characters are UCHAR encoded.
            out.append(_uchar(code))
            continue
        out.append(ch)
    return "".join(out)


def _escape_iri(iri_value):
    # IRIREF excludes U+0000..U+0020 and < > " { } | ^ ` \.
    out = []
    for ch in iri_value:
        code = ord(ch)
        if code <= 0x20 or ch in '<>"{}|^`\\':
            out.append(_uchar(code))
        else:
            out.append(ch)
    return "".join(out)


def serialize_term(term, bnode_labels=None):
    """Serialize one RDF term in canonical N-Quads form.

    ``bnode_labels`` maps blank-node labels to their canonical labels
    (typically the issued identifiers map); when omitted, labels are emitted
    unchanged (used by first-degree hashing, where callers pass rewritten
    placeholder labels ``a``/``z``).
    """
    kind = term[0]
    if kind == IRI:
        return "<%s>" % _escape_iri(term[1])
    if kind == BNODE:
        label = term[1]
        if bnode_labels is not None:
            label = bnode_labels[label]
        return "_:%s" % label
    if kind == LITERAL:
        _, lexical, language, datatype = term
        body = '"%s"' % _escape_literal(lexical)
        if language is not None:
            body += "@" + language
        elif datatype is not None and datatype != XSD_STRING:
            body += "^^<%s>" % _escape_iri(datatype)
        return body
    raise ValueError("unknown term kind %r" % (term,))


def serialize_quad(quad, bnode_labels=None):
    subject, predicate, obj, graph = quad
    parts = [
        serialize_term(subject, bnode_labels),
        serialize_term(predicate, bnode_labels),
        serialize_term(obj, bnode_labels),
    ]
    if graph is not None:
        parts.append(serialize_term(graph, bnode_labels))
    return " ".join(parts) + " .\n"


def canonical_nquads(quads, bnode_labels=None):
    """Return the canonical N-Quads document for a (canonicalized) dataset.

    Each quad is serialized, sorted by code point order, concatenated.  The
    empty dataset serializes to the empty string.
    """
    lines = [serialize_quad(q, bnode_labels) for q in quads]
    lines.sort()
    return "".join(lines)


def canonical_sha256(canonical_text):
    """SHA-256 over the UTF-8 bytes of the canonical document."""
    return hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()


def build_result(quads, bnode_labels):
    canonical = canonical_nquads(quads, bnode_labels)
    return {"canonical": canonical, "sha256": canonical_sha256(canonical)}


def render_result_json(result):
    """Render the output object with stable key order and a trailing LF."""
    return json.dumps(result, ensure_ascii=False, indent=2) + "\n"


def atomic_write(path, payload_text):
    """Replace ``path`` only after a fully successful write.

    The payload is first written and fsynced in a temporary file in the same
    directory, then atomically renamed over the target.  A failure before the
    rename leaves any pre-existing output file untouched.
    """
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(prefix=".rdfc10-", suffix=".tmp",
                                    dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(payload_text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
