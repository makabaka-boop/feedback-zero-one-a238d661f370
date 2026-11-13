"""RDFC-1.0 canonicalization algorithm (W3C REC 2024-05-21, section 4).

Implements, in order:

* 4.4.3 Canonicalization Algorithm;
* 4.5   Issue Identifier Algorithm (:class:`IdentifierIssuer`);
* 4.6   Hash First Degree Quads;
* 4.7   Hash Related Blank Node;
* 4.8   Hash N-Degree Quads, including multi-degree adjudication after a
        first-degree hash collision and the standard's early termination
        rule for gossip-path permutations.

The internal hash is fixed to SHA-256.  Poison detection and resource
termination are intentionally disabled: every legal finite input runs to
completion, as required.
"""

import hashlib
import sys

from .terms import BNODE
from .serialize import serialize_quad

# The N-degree recursion depth is bounded by the number of blank nodes; give
# deeply connected but perfectly legal finite datasets room to run.
sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))


def _sha256_hex(data):
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class IdentifierIssuer:
    """Section 4.5 identifier issuer (prefix ``c14n`` or temporary ``b``)."""

    def __init__(self, prefix):
        self.prefix = prefix
        self._counter = 0
        #: existing identifier -> issued identifier, in issuance order
        self.issued = {}

    def copy(self):
        clone = IdentifierIssuer(self.prefix)
        clone._counter = self._counter
        clone.issued = dict(self.issued)
        return clone

    def issue(self, existing):
        issued = self.issued.get(existing)
        if issued is not None:
            return issued
        issued = "%s%d" % (self.prefix, self._counter)
        self.issued[existing] = issued
        self._counter += 1
        return issued

    def has(self, existing):
        return existing in self.issued


class CanonicalState:
    """Section 4.2 canonicalization state (SHA-256 variant)."""

    def __init__(self, quads):
        self.quads = quads
        # blank node identifier -> list of quads mentioning it
        self.bnode_to_quads = {}
        # first-degree hash cache, section 4.7 note
        self.hash_cache = {}
        # the single canonical issuer (prefix c14n)
        self.canonical_issuer = IdentifierIssuer("c14n")
        self._index_quads()

    def _index_quads(self):
        # The blank node to quads map holds a *set* of quads per identifier:
        # duplicate input quads are collapsed at parse time and, even if the
        # same quad reaches this routine twice, it must appear exactly once
        # when the mention set is serialized (sections 4.4.3 step 2 and
        # 4.6.3).  Quad tuples are hashable, so a set enforces this directly.
        for quad in self.quads:
            for component in quad:
                if component is not None and component[0] == BNODE:
                    self.bnode_to_quads.setdefault(
                        component[1], set()).add(quad)

    # -- section 4.6 --------------------------------------------------------

    def hash_first_degree(self, reference):
        cached = self.hash_cache.get(reference)
        if cached is not None:
            return cached
        serialized = []
        for quad in self.bnode_to_quads[reference]:
            serialized.append(
                serialize_quad(
                    quad,
                    bnode_labels=_FirstDegreeLabels(reference),
                )
            )
        serialized.sort()
        result = _sha256_hex("".join(serialized))
        self.hash_cache[reference] = result
        return result

    # -- section 4.7 --------------------------------------------------------

    def hash_related_blank_node(self, related, quad, position, issuer):
        predicate = quad[1][1]
        if position == "g":
            data = "g"
        else:
            data = "%s<%s>" % (position, predicate)

        canonical_id = self.canonical_issuer.issued.get(related)
        if canonical_id is not None:
            data += "_:" + canonical_id
        elif issuer.has(related):
            data += "_:" + issuer.issued[related]
        else:
            data += self.hash_first_degree(related)
        return _sha256_hex(data)

    # -- section 4.8 --------------------------------------------------------

    def hash_n_degree_quads(self, identifier, issuer, memo=None):
        """Section 4.8 Hash N-Degree Quads.

        ``memo`` is a root-call-local result cache.  The result of this
        procedure is determined solely by the reference identifier and the
        contents of the path identifier issuer; within one root call the
        canonical issuer never changes, so equal states always produce equal
        results.  On highly symmetric graphs the same state is reached from
        many permutations, and memoizing those states turns an otherwise
        factorial traversal into one over distinct (sub)graph states without
        changing any result.  Cached issuers are handed back as copies
        because callers continue to issue identifiers on them.
        """
        if memo is None:
            memo = {}
        # The key is the reference identifier plus the *content* of the path
        # issuer (existing-id -> temporary-id), independent of insertion
        # order.  A frozenset captures that mapping without sorting.
        memo_key = (identifier, frozenset(issuer.issued.items()))
        cached = memo.get(memo_key)
        if cached is not None:
            return {"hash": cached["hash"],
                    "issuer": cached["issuer"].copy()}

        # Step 3: build Hn, related hash -> related blank node labels.
        hn = {}
        for quad in self.bnode_to_quads[identifier]:
            for position, component in (
                ("s", quad[0]),
                ("o", quad[2]),
                ("g", quad[3]),
            ):
                if component is None or component[0] != BNODE:
                    continue
                related = component[1]
                if related == identifier:
                    continue
                related_hash = self.hash_related_blank_node(
                    related, quad, position, issuer)
                hn.setdefault(related_hash, []).append(related)

        # Step 4/5: walk related hashes in code point order.
        data_to_hash = ""
        for related_hash in sorted(hn):
            data_to_hash += related_hash

            blank_node_list = hn[related_hash]
            chosen_path = ""
            chosen_issuer = None

            # Step 5.4: every *distinct* permutation of the related list,
            # generated lazily in lexicographic order.  Repeated entries
            # yield identical permutations; evaluating one copy of each
            # distinct permutation gives exactly the standard's chosen path
            # and issuer while keeping the work finite on fully symmetric
            # graphs.  Permutations are produced on demand so the early
            # termination clauses below can prune before the remaining
            # (potentially factorial-sized) work is ever materialized.
            for permutation in _multiset_permutations(blank_node_list):
                issuer_copy = issuer.copy()
                path = ""
                recursion_list = []
                skip_permutation = False

                for related in permutation:
                    canonical_id = self.canonical_issuer.issued.get(related)
                    if canonical_id is not None:
                        path += "_:" + canonical_id
                    else:
                        if not issuer_copy.has(related):
                            recursion_list.append(related)
                        path += "_:" + issuer_copy.issue(related)

                    # Early termination clause of step 5.4.4.  Once a partial
                    # path is already code-point greater than the chosen path
                    # it can never become smaller by extension, so prune.
                    if chosen_path and path > chosen_path:
                        skip_permutation = True
                        break

                if skip_permutation:
                    continue

                # Step 5.4.5: recurse over newly labeled related nodes.
                for related in recursion_list:
                    result = self.hash_n_degree_quads(
                        related, issuer_copy, memo)
                    path += "_:" + issuer_copy.issue(related)
                    path += "<%s>" % result["hash"]
                    issuer_copy = result["issuer"]

                    # Early termination clause of step 5.4.5.
                    if chosen_path and path > chosen_path:
                        skip_permutation = True
                        break

                if skip_permutation:
                    continue

                if not chosen_path or path < chosen_path:
                    chosen_path = path
                    chosen_issuer = issuer_copy

            data_to_hash += chosen_path
            # Step 6: continue with the issuer of the chosen path.
            issuer = chosen_issuer

        result = {
            "hash": _sha256_hex(data_to_hash),
            "issuer": issuer,
        }
        memo[memo_key] = {"hash": result["hash"],
                          "issuer": result["issuer"].copy()}
        # Return a fresh copy of the issuer so caller-side issuance cannot
        # mutate the cached state object.
        result["issuer"] = issuer.copy()
        return result


class _FirstDegreeLabels:
    """Label map used by section 4.6: reference -> 'a', others -> 'z'."""

    def __init__(self, reference):
        self.reference = reference

    def __contains__(self, label):
        return True

    def __getitem__(self, label):
        return "a" if label == self.reference else "z"


def _multiset_permutations(items):
    """Yield every distinct permutation of ``items`` lazily.

    Uses the classic lexicographic "next permutation" algorithm on a sorted
    multiset, which visits each *distinct* ordering exactly once without
    ever materializing the full (potentially factorial-sized) list.  Blank
    node labels are strings, so plain code point ordering applies.
    """
    current = sorted(items)
    size = len(current)
    if size == 0:
        return
    yield tuple(current)
    while True:
        # Find the largest pivot index i with current[i] < current[i+1].
        pivot = size - 2
        while pivot >= 0 and current[pivot] >= current[pivot + 1]:
            pivot -= 1
        if pivot < 0:
            return
        # Find the largest j > pivot with current[j] > current[pivot].
        successor = size - 1
        while current[successor] <= current[pivot]:
            successor -= 1
        current[pivot], current[successor] = (
            current[successor], current[pivot])
        current[pivot + 1:] = reversed(current[pivot + 1:])
        yield tuple(current)


# ---------------------------------------------------------------------------
# Section 4.4.3 top-level algorithm
# ---------------------------------------------------------------------------


def canonicalize(quads):
    """Canonicalize a dataset (set of quad tuples).

    Returns a dict mapping every blank-node label in the input to its
    issued canonical label (the canonical issuer's issued identifiers map).
    """
    state = CanonicalState(quads)

    # Step 3: first-degree hashes for every blank node.
    hash_to_bnodes = {}
    for label in state.bnode_to_quads:
        first_hash = state.hash_first_degree(label)
        hash_to_bnodes.setdefault(first_hash, []).append(label)

    # Step 4: canonically label uniquely hashed nodes.  Entries of the hash
    # to blank nodes map are processed code point ordered by hash; a unique
    # hash maps to exactly one node, which receives the next canonical id.
    for first_hash in sorted(hash_to_bnodes):
        labels = hash_to_bnodes[first_hash]
        if len(labels) == 1:
            state.canonical_issuer.issue(labels[0])

    # Step 5: N-degree hashes for the remaining, colliding hash groups.
    remaining = {
        h: labels
        for h, labels in hash_to_bnodes.items()
        if len(labels) > 1
    }
    for first_hash in sorted(remaining):
        identifier_list = remaining[first_hash]
        hash_path_list = []

        # Step 5.2.
        for label in identifier_list:
            if state.canonical_issuer.has(label):
                continue
            temporary_issuer = IdentifierIssuer("b")
            temporary_issuer.issue(label)
            result = state.hash_n_degree_quads(label, temporary_issuer)
            hash_path_list.append(result)

        # Step 5.3: issue canonical labels in N-degree hash order, keeping
        # the temporary issuer's issuance order within each result.
        hash_path_list.sort(key=lambda result: result["hash"])
        for result in hash_path_list:
            for existing in result["issuer"].issued:
                if not state.canonical_issuer.has(existing):
                    state.canonical_issuer.issue(existing)

    return dict(state.canonical_issuer.issued)
