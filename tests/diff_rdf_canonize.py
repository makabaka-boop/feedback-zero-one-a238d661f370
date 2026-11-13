#!/usr/bin/env python3 -I
"""Differential testing against the mature rdf-canonize implementation.

Generates many random datasets from the common legal N-Quads subset
(IRIs, blank nodes, plain/language/tagged literals, default and IRI/blank
named graphs, duplicate quads, comments and varied whitespace), canonicalizes
each with both this implementation and Digital Bazaar's rdf-canonize
(RDFC-1.0, SHA-256), and asserts the canonical documents and digests are
byte-identical.

rdf-canonize is a development-only dependency living under third_party/ref;
it is never imported by the delivered package.
"""

import json
import os
import random
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                "..", "src")))

from rdfc10nq import (  # noqa: E402
    parse_nquads,
    canonicalize,
    canonical_nquads,
    canonical_sha256,
)

REF_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                       "third_party", "ref"))

IRIS = [
    "http://example.org/a",
    "http://example.org/ns#p1",
    "urn:ex:zz",
    "http://example.org/∞",
    # Raw space is illegal inside IRIREF; exercise the UCHAR form instead.
    "http://example.org/space\\u0020here",
    "http://example.org/brace\\u007B",
]
BLANKS = ["e0", "e1", "e2", "b", "énode", "x.y"]
LITERALS = [
    '"hello"',
    '""',
    '"line\\nbreak"',
    '"tab\\there"',
    '"quote\\"q"',
    '"unicode é 中 \U0001f303"',
    '"42"^^<http://www.w3.org/2001/XMLSchema#integer>',
    '"1"^^<urn:ex:dt>',
    '"01"^^<http://www.w3.org/2001/XMLSchema#integer>',
    '"s"@en',
    '"s"@en-gb-oxford',
    '"s"@zh-hans',
    # A literal carrying UCHAR-escaped and ECHAR-escaped characters.
    '"\\u0009\\u000b control"',
]


def term(rng):
    kind = rng.randrange(7)
    if kind <= 2:
        return "<%s>" % rng.choice(IRIS)
    if kind <= 4:
        return "_:%s" % rng.choice(BLANKS)
    return rng.choice(LITERALS)


def make_dataset(rng):
    lines = []
    count = rng.randrange(1, 40)
    for _ in range(count):
        subject = term(rng)
        while subject.startswith('"'):
            subject = term(rng)
        predicate = "<%s>" % rng.choice(IRIS)
        obj = term(rng)
        parts = [subject, predicate, obj]
        if rng.random() < 0.45:
            graph = term(rng)
            while graph.startswith('"'):
                graph = term(rng)
            parts.append(graph)
        line = " ".join(parts) + " ."
        # Sprinkle legal whitespace variety.  Standalone comment lines are
        # valid per N-Quads 1.1 but are not accepted by rdf-canonize's
        # line-regex parser, so they are exercised separately in the
        # independent acceptance suite rather than in this common-subset
        # differential test.
        if rng.random() < 0.2:
            line = "\t" + line.replace(" ", "  ", 1)
        lines.append(line)
    # Deliberately duplicate some quads to exercise set-based de-duplication.
    if lines and rng.random() < 0.5:
        lines.append(lines[0])
    rng.shuffle(lines)
    return ("\n".join(lines) + "\n").encode("utf-8")


def ref_canonize(raw_path):
    script = (
        "const rc=require('rdf-canonize');"
        "const fs=require('fs');"
        "const input=fs.readFileSync(process.argv[1],'utf8');"
        "rc.canonize(input,{algorithm:'RDFC-1.0',"
        "inputFormat:'application/n-quads'}).then("
        "out=>{process.stdout.write(out);}).catch(e=>{"
        "console.error('REF-ERROR:'+e.message);process.exit(2);});"
    )
    result = subprocess.run(
        ["node", "-e", script, raw_path],
        cwd=REF_DIR, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError("rdf-canonize failed: %s" % result.stderr)
    return result.stdout


def main():
    rng = random.Random(20240521)
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    mismatches = 0
    with tempfile.TemporaryDirectory() as tmp:
        for trial in range(trials):
            raw = make_dataset(rng)
            path = os.path.join(tmp, "case.nq")
            with open(path, "wb") as handle:
                handle.write(raw)

            quads = parse_nquads(raw)
            labels = canonicalize(quads)
            mine = canonical_nquads(quads, labels)
            mine_digest = canonical_sha256(mine)

            try:
                ref = ref_canonize(path)
            except RuntimeError:
                bad = "/tmp/rdfc-diff-ref-reject-%d.nq" % trial
                with open(bad, "wb") as handle:
                    handle.write(raw)
                print("rdf-canonize rejected trial %d (saved %s):\n%s"
                      % (trial, bad, raw.decode("utf-8")))
                raise

            if mine != ref:
                mismatches += 1
                bad = "/tmp/rdfc-diff-mismatch-%d.nq" % trial
                with open(bad, "wb") as handle:
                    handle.write(raw)
                print("MISMATCH trial %d (saved %s)" % (trial, bad))
                print("--- input ---\n%s" % raw.decode("utf-8"))
                print("--- mine ---\n%r" % mine)
                print("--- rdf-canonize ---\n%r" % ref)
                if mismatches >= 3:
                    break
                continue

            if mine_digest != canonical_sha256(ref):
                print("DIGEST MISMATCH trial %d" % trial)
                mismatches += 1
                break

    if mismatches:
        print("FAILED: %d mismatch(es) over %d trials" %
              (mismatches, trials))
        sys.exit(1)
    print("OK: %d random datasets byte-identical to rdf-canonize" % trials)


if __name__ == "__main__":
    main()
