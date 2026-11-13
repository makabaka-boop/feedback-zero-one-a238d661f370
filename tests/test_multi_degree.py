"""Targeted tests for the multi-degree adjudication after a first-degree
hash collision (RDFC-1.0 sections 4.7 and 4.8).

These structures make every blank node share an identical first-degree hash,
forcing the Hash N-Degree Quads recursion and its permutation/path selection.
Expected canonical labels are taken from the W3C fixed vectors, which are
also asserted byte-for-byte in test_w3c_vectors; here we additionally assert
the structural properties that demonstrate multi-degree handling.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                "..", "src")))

from rdfc10nq import (  # noqa: E402
    parse_nquads,
    canonicalize,
    canonical_nquads,
)

VECTOR_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "third_party", "w3c-rdf-canon",
    "tests", "rdfc10"))


def _vector(name):
    with open(os.path.join(VECTOR_DIR, name + "-in.nq"), "rb") as handle:
        raw = handle.read()
    with open(os.path.join(VECTOR_DIR, name + "-rdfc10.nq"), "rb") as handle:
        expected = handle.read().decode("utf-8")
    quads = parse_nquads(raw)
    labels = canonicalize(quads)
    return canonical_nquads(quads, labels), expected, labels


class MultiDegreeTest(unittest.TestCase):
    def test_symmetric_two_node_circle(self):
        # test021: every node has the same first-degree hash; N-degree
        # recursion must still produce a total, deterministic ordering.
        out, expected, labels = _vector("test021")
        self.assertEqual(out, expected)
        self.assertEqual(len(labels), 2)

    def test_symmetric_three_node_circle(self):
        out, expected, labels = _vector("test023")
        self.assertEqual(out, expected)
        self.assertEqual(len(labels), 3)

    def test_double_circle_permutations(self):
        # test024-029 are the six orderings of a double 3-circle; they are
        # isomorphic and must canonicalize identically.
        canonical_forms = set()
        for name in ("test024", "test025", "test026",
                     "test027", "test028", "test029"):
            out, expected, _ = _vector(name)
            self.assertEqual(out, expected)
            canonical_forms.add(out)
        self.assertEqual(len(canonical_forms), 1)

    def test_blank_node_graph_name(self):
        # test071: blank node used as a graph name participates in the same
        # identifier space and is reached via position 'g'.
        out, expected, labels = _vector("test071")
        self.assertEqual(out, expected)
        # The graph-name blank node must itself be canonically labeled.
        self.assertIn("_:c14n", out)

    def test_shared_bnodes_across_graphs(self):
        # test072/073: one blank node shared between default and named graph.
        for name in ("test072", "test073"):
            out, expected, _ = _vector(name)
            self.assertEqual(out, expected)

    def test_self_link_and_diamond(self):
        # test018 (self link) and test020 (diamond) stress recursion cycles.
        for name in ("test018", "test020"):
            out, expected, _ = _vector(name)
            self.assertEqual(out, expected)

    def test_escaping_round_trip(self):
        # test060: ECHAR/UCHAR/native code point canonical escaping.
        out, expected, _ = _vector("test060")
        self.assertEqual(out, expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
