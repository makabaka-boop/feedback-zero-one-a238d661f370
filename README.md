# RDFC-1.0 N-Quads Canonicalization Job

A from-scratch Python backend job that reads a **strict UTF-8 RDF 1.1
N-Quads (2014)** file and emits a JSON object containing only:

* `canonical` — the canonical N-Quads document produced by
  **RDF Dataset Canonicalization 1.0** (W3C REC 2024-05-21), sections 4 and 5
  and appendix A, using the fixed internal hash **SHA-256**;
* `sha256` — the lowercase hexadecimal SHA-256 digest of the UTF-8 bytes of
  `canonical`.

The runtime code depends only on the Python 3 standard library (`hashlib`
for digests). No RDF parser and **no canonicalization engine** is called;
parsing, canonical labeling and canonical serialization are all implemented
here.

## Layout

```
src/rdfc10nq/
  errors.py     # NQuadsParseError with LF-based physical line numbers
  terms.py      # hashable IRI / blank-node / literal terms and quads
  parser.py     # hand-written strict N-Quads 1.1 recursive-descent parser
  canon.py      # RDFC-1.0 sections 4.4-4.8 (incl. N-degree adjudication)
  serialize.py  # appendix A canonical N-Quads, digest, atomic JSON write
  __main__.py   # CLI entry point
bin/rdfc10-canon            # executable wrapper (runs Python with -I)
tests/
  test_w3c_vectors.py       # W3C fixed vectors, byte-exact
  test_acceptance.py        # strict parsing, semantics, atomic output
  test_multi_degree.py      # first-degree collision / N-degree cases
  diff_rdf_canonize.py      # differential check vs rdf-canonize (dev only)
  run_all.py                # runs the three unittest suites
third_party/                # downloaded spec + vectors + reference (not shipped deps)
```

## Usage

The recommended entry point is the wrapper, which runs the interpreter in
isolated mode (`-I`, so no environment site packages or working-directory
modules such as a planted `json.py` can be imported) and locates the package
relative to itself:

```sh
bin/rdfc10-canon INPUT.nq OUTPUT.json
```

Equivalent module invocation (note that `-I` ignores `PYTHONPATH`, so the
package is importable either via the wrapper or by placing `src/` on the
path in normal mode):

```sh
PYTHONPATH=src python3 -m rdfc10nq INPUT.nq OUTPUT.json
```

The output is written atomically: a temporary file in the target directory
is fully written and fsynced, then renamed over the destination. On any
validation or processing failure the process exits non-zero, reports the
offending **line number (counted from 1 over the LF bytes of the original
input)**, and leaves any pre-existing output file untouched.

Example:

```
$ printf '_:a <urn:p> "x" .\n' > in.nq
$ bin/rdfc10-canon in.nq out.json
$ cat out.json
{
  "canonical": "_:c14n0 <urn:p> \"x\" .\n",
  "sha256": "4995dc729b4837ab7e306874e9cc6be58f26aa85c4cb7fdcf1ea62a3dedaf29f"
}
```

The empty dataset yields `canonical: ""` and the SHA-256 of the empty byte
string (`e3b0c442…b855`).

## Conformance details

### Parsing (strict N-Quads 1.1, 2014 edition)

* Strict UTF-8 only; a leading BOM is rejected, invalid UTF-8 and invalid
  Unicode scalar values (surrogates, code points past U+10FFFF) fail the
  whole document.
* Only the 2014 grammar: `STRING_LITERAL_QUOTE` literals, IRIREF,
  BLANK_NODE_LABEL, `WS` = space/tab, EOL = one or more CR/LF, comments at
  statement boundaries. Triple-quoted strings and other-edition syntax are
  rejected.
* Language tags are restricted to ASCII **lower case** (upper case is
  rejected), per the task requirement.
* UCHAR (`\uXXXX` / `\UXXXXXXXX`) and ECHAR escapes are decoded; literal
  lexical values are retained verbatim — no numeric, Unicode or IRI
  normalization.
* Blank-node labels share one identity across the whole file. Duplicate
  quads are de-duplicated; quads that differ only by graph are never merged.

### Canonicalization (RDFC-1.0)

* 4.6 first-degree hashing with `a`/`z` placeholders;
* 4.5 identifier issuers (canonical prefix `c14n`, temporary prefix `b`);
* 4.7 related-blank-node hashing for positions `s`/`o`/`g`;
* 4.8 N-degree hashing with lazy distinct (multiset) permutation generation
  and the standard's in-loop early-termination clauses, so multi-degree
  adjudication after a first-degree collision is handled without
  materializing factorial-sized permutation lists;
* poison detection and resource termination are **disabled** — every legal
  finite input runs to completion.

### Serialization (section 5 + appendix A)

* single U+0020 separators, one LF per statement including the final one;
* ECHAR for U+0008/0009/000A/000C/000D/0022/005C; UCHAR (lowercase marker,
  uppercase hex) for U+0000–0007, U+000B, U+000E–001F, DEL and code points
  outside the XML 1.1 `Char` production; all other code points native;
* `xsd:string` datatype omitted; lines ordered by code point comparison.

## Verification

```sh
python3 -I tests/run_all.py
python3 -I tests/diff_rdf_canonize.py 1000   # needs Node + third_party/ref
```

* All 63 SHA-256 positive W3C fixed vectors match the expected canonical
  bytes exactly (covering symmetric circles, blank-node graph names,
  cross-graph shared blank nodes and escaping). `test075` (SHA-384 variant)
  and `test074` (the standard's optional negative poison test) are excluded.
* 34 independent acceptance tests and 7 targeted multi-degree tests pass.
* 1000 randomized common-subset datasets are byte-identical to Digital
  Bazaar's `rdf-canonize` RDFC-1.0 implementation.

### Note on test074 (10-node symmetric clique)

test074 is an `RDFC10NegativeEvalTest`: the RDFC-1.0 standard explicitly
permits implementations to reject it because the unconstrained algorithm is
factorial in the number of mutually-indistinguishable blank nodes. With
resource termination disabled (as this task requires), the implementation
still terminates correctly — it simply takes the algorithm's intrinsic
factorial time. Measured scaling on the complete symmetric clique K_n is
roughly 10x per added node:

| n | quads | wall time |
|---|-------|-----------|
| K6 | 36 | 0.1 s |
| K7 | 49 | 0.9 s |
| K8 | 64 | ~11 s |
| K9 | 81 | ~153 s |
| K10 (test074) | 100 | ~3438 s (~57 min), completes with 100 canonical statements |

`rdf-canonize` exhibits the same factorial growth when its own limits are
disabled, confirming this is a property of the standard's permutation search
rather than of this implementation. All tractable poison positive tests
(test044–046) complete in milliseconds. No implementation can make the fully
symmetric K10 terminate quickly while remaining faithful to the standard;
this implementation is correct and simply unbounded, as specified.
