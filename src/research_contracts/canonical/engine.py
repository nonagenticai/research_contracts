"""The released canonical hashing API (FND-005, shared foundation section 4.3).

``canonical_json_bytes`` and ``canonical_sha256`` are the only sanctioned entry points.
No service invents a local JSON sorting recipe for an approval, idempotency or
input-snapshot hash.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .errors import ContentHashMismatchError
from .hash_profile import derive_hash_profile, validate_profile_against_schema
from .hash_view import build_hash_view
from .jcs import canonicalize
from .structural import assert_valid_instance

__all__ = [
    "canonical_json_bytes",
    "canonical_sha256",
    "compute_content_hash",
    "verify_content_hash",
]

DIGEST_PREFIX = "sha256:"


def canonical_json_bytes(obj: Any, *, allow_binary_float: bool = False) -> bytes:
    """Return the RFC 8785 canonical UTF-8 bytes of ``obj``, without a byte-order mark.

    ``allow_binary_float`` exists only for RFC 8785 conformance vectors. Every released
    hash path leaves it ``False``, so an unstable binary float raises instead of being
    silently hashed.
    """
    return canonicalize(obj, allow_binary_float=allow_binary_float)


def canonical_sha256(obj: Any, *, allow_binary_float: bool = False) -> str:
    """Return ``sha256:<64-lowercase-hex>`` over the RFC 8785 canonical bytes of ``obj``."""
    digest = hashlib.sha256(canonical_json_bytes(obj, allow_binary_float=allow_binary_float))
    return DIGEST_PREFIX + digest.hexdigest()


def compute_content_hash(
    instance: Any,
    schema_ref: str,
    *,
    profile: dict[str, Any] | None = None,
) -> str:
    """Run the full ordered section 4.3 algorithm and return the canonical content hash.

    1. validate the fully composed object against its declared ``schema_ref``;
    2. build the schema-declared semantic hash view;
    3. remove only the schema-marked non-hashable paths (nested target ``content_hash``
       values remain included);
    4. enforce each array's released ordered/set-like declaration and sort set members;
    5. apply the released absent-versus-null, timestamp, Unicode and decimal rules;
    6. serialize as RFC 8785 canonical JSON, UTF-8, no byte-order mark; and
    7. SHA-256 over those exact bytes rendered as ``sha256:<64-lowercase-hex>``.
    """
    assert_valid_instance(instance, schema_ref)
    if profile is None:
        profile = derive_hash_profile(schema_ref)
    else:
        # A supplied manifest is checked against the schema's own annotations, not merely
        # against the manifest schema: a well-formed manifest that deletes an exclusion or
        # re-declares a released array would silently produce a second, contradictory
        # "canonical" hash for the same object.
        validate_profile_against_schema(profile, schema_ref)
    view = build_hash_view(instance, profile)
    return canonical_sha256(view)


def verify_content_hash(
    instance: Any,
    schema_ref: str,
    *,
    profile: dict[str, Any] | None = None,
    field: str = "content_hash",
) -> str:
    """Recompute ``instance[field]`` and fail closed on a mismatch.

    A supplied hash is never trusted (document 16 acceptance test DM-AT-29).
    """
    recomputed = compute_content_hash(instance, schema_ref, profile=profile)
    supplied = instance.get(field) if isinstance(instance, dict) else None
    if supplied is None:
        raise ContentHashMismatchError(
            f"{field} is absent; a canonical hash must be supplied to be verified"
        )
    if supplied != recomputed:
        raise ContentHashMismatchError(
            f"{field} does not recompute: supplied {supplied}, recomputed {recomputed}"
        )
    return recomputed
