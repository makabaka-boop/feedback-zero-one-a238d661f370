"""RDF term representation.

Terms are immutable, hashable tuples so datasets can be stored in ``set``
objects (duplicate quad removal) and used as map keys:

* IRI term:     ``(IRI, value)``
* blank node:   ``(BNODE, label)`` -- the shared, file-wide blank-node label
* literal:      ``(LITERAL, lexical_form, language, datatype_iri_or_None)``

A quad is a 4-tuple ``(subject, predicate, object, graph)`` where ``graph``
is either an IRI/blank-node term or ``None`` denoting the default graph.

Literal lexical values are retained verbatim after escape decoding; no value
space, Unicode, or IRI normalization is ever performed.
"""

IRI = "IRI"
BNODE = "BNODE"
LITERAL = "LITERAL"

#: The implicit datatype IRI of a language-tagged literal.
RDF_LANG_STRING = "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"

#: The implicit datatype IRI of a plain, untyped literal.
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"


def iri(value):
    return (IRI, value)


def bnode(label):
    return (BNODE, label)


def literal(lexical, language=None, datatype=None):
    return (LITERAL, lexical, language, datatype)
