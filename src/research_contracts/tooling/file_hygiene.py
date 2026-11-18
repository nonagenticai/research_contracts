"""Whitespace and final-newline hygiene as a CHECK that fails, never a rewrite.

The verified defect: ``.pre-commit-config.yaml`` ran the upstream
``end-of-file-fixer`` and ``trailing-whitespace`` hooks. Both *rewrite* tracked
files, and neither existed as a CI step — the exact local-stricter-than-CI
inversion the pre-commit config's own header forbids, in its most damaging form.

The replacement checks and reports; it never writes. It enumerates the tracked
files with ``git ls-files``, so the local hook and the CI step see one identical
file set — a filesystem walk would additionally see untracked scratch files
locally and reintroduce the inversion from the other direction.

The same gate rejects a raw NUL byte in a tracked file. It used to *skip* one --
``if b"\\x00" in data: continue`` -- and a single 0x00 at offset 22323 of
``packages/typescript/src/structural.ts`` therefore passed while making all 870
lines of that file invisible to ``file``, ``grep``, ripgrep and
``gh search code``. A file no scanner can read is the evasion this gate exists to
prevent, so it is now an error with a named-path exemption (:data:`BINARY_BYTE_FILES`).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

from .errors import ContractError
from .paths import REPOSITORY_ROOT

#: Tracked files permitted to contain a raw NUL (0x00), by exact path.
#:
#: Deliberately empty, and that is a measurement rather than an omission: no tracked file in
#: this repository is binary (:func:`nul_byte_errors` recomputes it on every run). A genuine
#: binary fixture may be added here, but it has to be named -- the previous behaviour was to
#: skip EVERY file containing a NUL, which is how ``packages/typescript/src/structural.ts``
#: carried one for its whole life while passing this gate.
#:
#: A raw NUL makes a text file invisible to the tools every audit is built on. With one byte
#: at offset 22323, ``file`` reported ``data``, ``grep -n const`` printed nothing and exited
#: 1, and ripgrep and ``gh search code`` returned no hits at all -- not "binary file matches",
#: nothing. All 870 lines of the cross-field collector were structurally unreachable to any
#: repository-wide census, secret scan or keyword audit. A file the scanners cannot read is
#: precisely the evasion this gate exists to prevent, so it is an error and never a skip.
#: The escape (``\x00`` in source) produces the identical runtime value and stays text.
BINARY_BYTE_FILES: Final[tuple[str, ...]] = ()

#: Bytes treated as trailing whitespace at the end of a line.
TRAILING_WHITESPACE: Final = (b" ", b"\t", b"\r", b"\x0b", b"\x0c")

REMEDIATION: Final = (
    "fix: strip the trailing whitespace, and end each file with exactly one newline "
    "(`printf '%s\\n' \"$(cat FILE)\" > FILE` for the final-newline cases). "
    "These are reported, never rewritten: a hook that edits a tracked file mid-commit "
    "can silently re-digest bytes another record depends on."
)


def git_free_env() -> dict[str, str]:
    """The ambient environment with every ``GIT_*`` variable removed.

    ``cwd=`` does not isolate a ``git`` subprocess. Git exports ``GIT_DIR`` and
    ``GIT_INDEX_FILE`` into every hook it runs and those outrank the working
    directory, so a ``git`` call made from a hook operates on the *inherited*
    repository. This gate runs as a pre-commit hook and enumerates with ``git``,
    so it strips them; ``--root`` then means what it says.
    """
    return {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}


def tracked_files(root: Path) -> list[str]:
    """Every path in ``root``'s git index, as repository-relative strings.

    Fails loudly rather than returning ``[]``. An enumeration that silently
    produced nothing would render as a clean tree — the defect class this
    repository exists to eliminate.
    """
    git = shutil.which("git")
    if git is None:
        raise ContractError("git is not on PATH, so the tracked file set cannot be enumerated")
    result = subprocess.run(  # noqa: S603 - absolute path from shutil.which, fixed argv
        [git, "ls-files", "-z"],
        check=False,
        capture_output=True,
        cwd=str(root),
        env=git_free_env(),
    )
    if result.returncode != 0:
        raise ContractError(
            f"{root}: `git ls-files` exited {result.returncode}: "
            f"{result.stderr.decode('utf-8', 'replace').strip()}"
        )
    names = [name for name in result.stdout.decode("utf-8").split("\0") if name]
    if not names:
        raise ContractError(f"{root}: `git ls-files` listed no files; an empty tree is not a clean")
    return sorted(names)


def whitespace_errors(root: Path, names: list[str]) -> list[str]:
    """Trailing-whitespace and final-newline violations, as diagnostics."""
    errors: list[str] = []
    for name in names:
        path = root / name
        if path.is_symlink() or not path.is_file():
            continue
        data = path.read_bytes()
        if b"\x00" in data:
            # Reported by nul_byte_errors, which is where the diagnostic belongs. The
            # line-oriented rules below would only add noise about a file no text tool can
            # read in the first place.
            continue
        if not data:
            continue
        for number, line in enumerate(data.split(b"\n"), start=1):
            if line.endswith(TRAILING_WHITESPACE):
                errors.append(f"{name}:{number}: trailing whitespace")
        if not data.endswith(b"\n"):
            errors.append(f"{name}: does not end with a newline")
        elif data.endswith(b"\n\n"):
            errors.append(f"{name}: ends with more than one newline")
    return errors


def nul_byte_errors(root: Path, names: list[str]) -> list[str]:
    """A tracked file carrying a raw NUL is an error unless it is a named binary.

    See :data:`BINARY_BYTE_FILES` for why. The exemption list is checked in the same pass
    and in both directions: a path listed there that does NOT carry a NUL is a stale
    exemption, and a stale exemption is how the next raw NUL would get skipped silently.
    """
    errors: list[str] = []
    exempt_seen: set[str] = set()
    for name in names:
        path = root / name
        if path.is_symlink() or not path.is_file():
            continue
        data = path.read_bytes()
        if b"\x00" not in data:
            continue
        if name in BINARY_BYTE_FILES:
            exempt_seen.add(name)
            continue
        errors.append(
            f"{name}:{data.index(b'\x00')}: raw NUL byte (0x00) in a tracked text file. "
            "`file` reports it as data and grep/ripgrep/`gh search code` return NOTHING for "
            "it, so every repository-wide census, secret scan and keyword audit is blind to "
            "the whole file. Write the escape (\\x00, \\u0000) instead, or add the path to "
            "BINARY_BYTE_FILES if it is genuinely a binary fixture."
        )
    for name in BINARY_BYTE_FILES:
        if name not in exempt_seen:
            errors.append(
                f"{name}: is listed in BINARY_BYTE_FILES but is not a tracked file carrying a "
                "NUL byte; a stale exemption is how the next unreadable file gets skipped"
            )
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check trailing whitespace and final newlines in tracked files."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="repository to check; defaults to the repository containing this file",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).expanduser().resolve()

    try:
        names = tracked_files(root)
        errors = whitespace_errors(root, names) + nul_byte_errors(root, names)
    except ContractError as exc:
        print(exc, file=sys.stderr)
        return 1

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        print(REMEDIATION, file=sys.stderr)
        print(
            f"{len(errors)} file hygiene violations across {len(names)} tracked files",
            file=sys.stderr,
        )
        return 1

    print(f"file hygiene passed: {len(names)} tracked files")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
