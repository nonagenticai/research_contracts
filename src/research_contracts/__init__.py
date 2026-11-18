"""Language-neutral research contract sources with their released Python helpers.

Two subpackages:

* :mod:`research_contracts.tooling` — the importable implementations behind the
  repository's contract gates (FND-001);
* :mod:`research_contracts.canonical` — the canonical serialization, hash-view
  and reference primitives (FND-002 and FND-005).
"""

#: Kept in lockstep with ``[project].version`` in ``pyproject.toml``. CI enforces
#: it (``require_version_sync: true``) rather than trusting the convention: a
#: consumer that seals an artifact with this engine records the version that
#: produced the hash, so "which version computed this digest?" must have exactly
#: one answer.
__version__ = "0.9.3"
