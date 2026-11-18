"""YAML loading that refuses duplicate mapping keys.

PyYAML is last-wins on duplicate keys and says nothing. That is a silent
information-destroying parse, and both gates in this repository were blind to
it:

* ``OWNERS.yaml`` could declare ``lifecycle: released`` and then
  ``lifecycle: draft``; the governance gate read the reassuring half of a file
  that says both things;
* a scanned contract document could declare ``kind: legal_event`` and then
  ``kind: research_asset``; the denylist never saw the first value because the
  parser had already thrown it away.

The loader is a :class:`yaml.SafeLoader` subclass and is driven through the
loader API rather than :func:`yaml.load`, so no construction of arbitrary
objects is possible and no security suppression is needed.
"""

from __future__ import annotations

from typing import Any

import yaml
import yaml.resolver


class DuplicateKeyError(yaml.YAMLError):
    """A YAML mapping declared the same key twice."""


class StrictLoader(yaml.SafeLoader):
    """``SafeLoader`` that raises :class:`DuplicateKeyError` on a duplicate key."""


def _construct_mapping(loader: StrictLoader, node: yaml.MappingNode, deep: bool = False) -> Any:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in seen
        except TypeError:  # unhashable key; YAML construction will reject it anyway
            continue
        if duplicate:
            raise DuplicateKeyError(
                f"duplicate key {key!r} at line {key_node.start_mark.line + 1}: a document that "
                "declares a key twice says two things, and the parser keeps only the last"
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def strict_yaml_load(text: str) -> Any:
    """Parse ``text`` as YAML, raising :class:`yaml.YAMLError` on duplicate keys."""
    loader = StrictLoader(text)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()
