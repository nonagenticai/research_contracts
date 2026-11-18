"""Canonical serialization, hash-view and reference primitives (FND-002 and FND-005)."""

from __future__ import annotations

from .engine import (
    DIGEST_PREFIX,
    canonical_json_bytes,
    canonical_sha256,
    compute_content_hash,
    verify_content_hash,
)
from .errors import (
    CanonicalError,
    ContentHashMismatchError,
    CrossFieldError,
    DuplicateSetMemberError,
    HashProfileError,
    MissingOrderKeyError,
    SchemaValidationError,
    UndeclaredArrayError,
    UnknownExclusionError,
    UnstableFloatError,
    UnsupportedTypeError,
)
from .hash_profile import (
    EXTENSIBLE_PROFILE_KEYS,
    derive_hash_profile,
    merge_profile_extensions,
    validate_hash_profile,
    validate_profile_against_schema,
)
from .hash_view import UndeclaredPathError, build_hash_view
from .jcs import canonicalize, es_number_to_string, stable_integer, utf16_sort_key
from .registry import (
    CANONICAL_SCHEMA_DIR,
    REPOSITORY_ROOT,
    canonical_schemas,
    schema_registry,
    validate_schema_only,
    validator_for,
)
from .structural import (
    assert_valid_instance,
    check_cross_field_rules,
    collect_cross_field_rules,
    validate_instance,
)
from .verification import (
    COMPARED_FIELDS,
    build_receipt,
    compare_pin_to_owner_response,
    verify_reference,
)

__all__ = [
    "CANONICAL_SCHEMA_DIR",
    "COMPARED_FIELDS",
    "DIGEST_PREFIX",
    "EXTENSIBLE_PROFILE_KEYS",
    "REPOSITORY_ROOT",
    "CanonicalError",
    "ContentHashMismatchError",
    "CrossFieldError",
    "DuplicateSetMemberError",
    "HashProfileError",
    "MissingOrderKeyError",
    "SchemaValidationError",
    "UndeclaredArrayError",
    "UndeclaredPathError",
    "UnknownExclusionError",
    "UnstableFloatError",
    "UnsupportedTypeError",
    "assert_valid_instance",
    "build_hash_view",
    "build_receipt",
    "canonical_json_bytes",
    "canonical_schemas",
    "canonical_sha256",
    "canonicalize",
    "check_cross_field_rules",
    "collect_cross_field_rules",
    "compare_pin_to_owner_response",
    "compute_content_hash",
    "derive_hash_profile",
    "es_number_to_string",
    "merge_profile_extensions",
    "schema_registry",
    "stable_integer",
    "utf16_sort_key",
    "validate_hash_profile",
    "validate_instance",
    "validate_profile_against_schema",
    "validate_schema_only",
    "validator_for",
    "verify_content_hash",
    "verify_reference",
]
