#!/usr/bin/python3 -I
"""Run the full acceptance suite in one go.

Order of execution:
  1. W3C RDFC-1.0 fixed vectors (byte-exact canonical output + digest);
  2. independent strict-parsing / semantics / atomic-output acceptance;
  3. targeted multi-degree adjudication cases.

The differential cross-check against rdf-canonize is a separate, optional
script because it requires Node and the development-only reference install:

    python3 -I tests/diff_rdf_canonize.py 1000
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "src")))
sys.path.insert(0, HERE)

loader = unittest.TestLoader()
suite = unittest.TestSuite()
for module in ("test_w3c_vectors", "test_acceptance", "test_multi_degree"):
    suite.addTests(loader.loadTestsFromName(module))

result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
