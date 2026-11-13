"""Command line entry point.

Usage:
    python -m rdfc10nq IN.nq OUT.json [--no-atomic]

Reads strict UTF-8 N-Quads bytes from ``IN.nq`` and writes a JSON object
containing exactly the two string fields ``canonical`` and ``sha256`` to
``OUT.json``.  On success the output is atomically replaced; on any
validation or canonicalization failure the previous output file is left
untouched and an error including the offending line number is written to
standard error with exit status 1.
"""

import argparse
import sys

from .errors import NQuadsParseError
from .parser import parse_nquads
from .canon import canonicalize
from .serialize import build_result, render_result_json, atomic_write


def run(input_path, output_path):
    with open(input_path, "rb") as handle:
        raw = handle.read()

    quads = parse_nquads(raw)
    bnode_labels = canonicalize(quads)
    result = build_result(quads, bnode_labels)
    atomic_write(output_path, render_result_json(result))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="rdfc10-canon",
        description="RDFC-1.0 (SHA-256) N-Quads canonicalization job")
    parser.add_argument("input", help="path to a strict UTF-8 N-Quads file")
    parser.add_argument("output", help="path of the JSON result to write")
    args = parser.parse_args(argv)

    try:
        result = run(args.input, args.output)
    except NQuadsParseError as exc:
        sys.stderr.write(
            "rdfc10-canon: rejected %s: %s\n" % (args.input, exc))
        return 1
    except OSError as exc:
        sys.stderr.write("rdfc10-canon: I/O failure: %s\n" % exc)
        return 1

    sys.stdout.write(
        "rdfc10-canon: wrote %s (sha256=%s, %d canonical statement(s))\n"
        % (args.output, result["sha256"],
           result["canonical"].count("\n")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
