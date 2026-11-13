"""Acceptance test 1: W3C RDFC-1.0 fixed test vectors.

Runs every SHA-256 positive evaluation test in
``third_party/w3c-rdf-canon/tests/rdfc10`` (the official W3C
rdf-canon repository snapshot) and compares the canonical N-Quads bytes and
the SHA-256 digest against the fixed expected outputs.

Excluded:
  * test074 -- RDFC10NegativeEvalTest (poison graph the standard permits
    implementations to reject; our brief disables resource termination);
  * test075 -- the SHA-384 hash algorithm variant (this job fixes SHA-256).

Run with: python3 -I tests/test_w3c_vectors.py
"""

import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                "..", "src")))

from rdfc10nq import (  # noqa: E402
    NQuadsParseError,
    parse_nquads,
    canonicalize,
    canonical_nquads,
    canonical_sha256,
)

VECTOR_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "third_party", "w3c-rdf-canon",
    "tests", "rdfc10"))

SKIP = {"test074", "test075"}


def _vector_names():
    names = set()
    for entry in os.listdir(VECTOR_DIR):
        if entry.endswith("-in.nq"):
            names.add(entry[:-len("-in.nq")])
    return sorted(n for n in names if n not in SKIP)


class W3CFixedVectorsTest(unittest.TestCase):
    def test_all_vectors(self):
        failures = []
        for name in _vector_names():
            in_path = os.path.join(VECTOR_DIR, name + "-in.nq")
            out_path = os.path.join(VECTOR_DIR, name + "-rdfc10.nq")
            with open(in_path, "rb") as handle:
                raw = handle.read()
            with open(out_path, "rb") as handle:
                expected_bytes = handle.read()

            quads = parse_nquads(raw)
            labels = canonicalize(quads)
            canonical = canonical_nquads(quads, labels)
            digest = canonical_sha256(canonical)

            actual_bytes = canonical.encode("utf-8")
            if actual_bytes != expected_bytes:
                # Locate the first differing byte for a readable failure.
                diff = next(
                    (i for i, (a, b) in enumerate(
                        zip(actual_bytes, expected_bytes)) if a != b),
                    min(len(actual_bytes), len(expected_bytes)))
                failures.append(
                    "%s: canonical byte mismatch at offset %d "
                    "(actual %d bytes vs expected %d)"
                    % (name, diff, len(actual_bytes), len(expected_bytes)))
                continue

            expected_digest = hashlib.sha256(expected_bytes).hexdigest()
            if digest != expected_digest:
                failures.append(
                    "%s: digest mismatch %s != %s"
                    % (name, digest, expected_digest))

        if failures:
            self.fail("\n".join(failures))

    def test_empty_dataset(self):
        # Empty input -> empty canonical string and its well-defined digest.
        labels = canonicalize(set())
        self.assertEqual(canonical_nquads(set(), labels), "")
        self.assertEqual(
            canonical_sha256(""),
            hashlib.sha256(b"").hexdigest())

    def test_vector_count_is_complete(self):
        # Guards against an accidental path/filtering regression.
        self.assertGreaterEqual(len(_vector_names()), 63)


if __name__ == "__main__":
    unittest.main(verbosity=2)
