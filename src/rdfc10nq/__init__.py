"""RDFC-1.0 N-Quads canonicalization backend.

A from-scratch, standard-library-only implementation of:

* a strict RDF 1.1 N-Quads (2014) parser;
* the RDF Dataset Canonicalization 1.0 algorithm
  (W3C REC 2024-05-21, sections 4 and 5 and appendix A) using SHA-256;
* canonical N-Quads serialization.

No external RDF or canonicalization library is used at runtime; only the
standard ``hashlib`` digest facility is relied upon for hashing.
"""

from .errors import NQuadsParseError
from .parser import parse_nquads
from .canon import canonicalize
from .serialize import (
    canonical_nquads,
    canonical_sha256,
    build_result,
    render_result_json,
    atomic_write,
)

__all__ = [
    "NQuadsParseError",
    "parse_nquads",
    "canonicalize",
    "canonical_nquads",
    "canonical_sha256",
    "build_result",
    "render_result_json",
    "atomic_write",
]
