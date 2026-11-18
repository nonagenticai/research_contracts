"""The single deterministic failure type raised by contract gates."""

from __future__ import annotations


class ContractError(ValueError):
    """A deterministic contract validation failure.

    Raised only for conditions the gate has actually diagnosed. Never used to
    absorb unexpected exceptions: a bug in a gate must surface as a traceback,
    not be relabelled as a contract violation.
    """
