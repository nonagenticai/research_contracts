"""Deterministic failure classes for the canonical hash engine (FND-005)."""

from __future__ import annotations


class CanonicalError(ValueError):
    """Base class for every canonical serialization or hash failure."""


class SchemaValidationError(CanonicalError):
    """Step 1: the object does not validate against its declared ``schema_ref``."""


class CrossFieldError(CanonicalError):
    """A released cross-field rule that JSON Schema cannot express failed."""


class HashProfileError(CanonicalError):
    """The released hash-view manifest is missing, malformed, or does not match its schema."""


class UnknownExclusionError(HashProfileError):
    """A hash exclusion whose reason is not in the released closed set."""


class UndeclaredArrayError(CanonicalError):
    """Step 4: an array with no released ordered/set-like declaration."""


class DuplicateSetMemberError(CanonicalError):
    """Step 4: a set-like array contains two members with the same canonical order key."""


class MissingOrderKeyError(CanonicalError):
    """Step 4: a set-like member does not carry a released order-key path at all.

    Distinct from ``DuplicateSetMemberError``: an absent order key is a manifest or data
    fault, not evidence that two members are the same member. Two members that both carry
    an explicit ``null`` at the order key *are* duplicates and still fail as such.
    """


class UnstableFloatError(CanonicalError):
    """Step 5: an unstable binary floating-point value may never enter a hashed input."""


class UnsupportedTypeError(CanonicalError):
    """A value that RFC 8785 cannot canonicalize."""


class ContentHashMismatchError(CanonicalError):
    """A supplied ``content_hash`` does not recompute. Supplied hashes are never trusted."""
