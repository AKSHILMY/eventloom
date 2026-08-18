"""Version-neutral helpers for payloads that are Pydantic-v1-style instead of
the Pydantic v2 this package otherwise targets throughout `core`.

`StreamEnvelope`/`EventEmitter` themselves are always Pydantic v2 — that never
changes. But `StreamEnvelope.data` (and `EventTypeSpec.schema`) are allowed to
be *any* Pydantic model, and `eventloom.contrib.pydantic_v1` (see its module
docstring) produces genuine Pydantic-v1-style instances — either from a real
`pydantic<2` install, or from Pydantic v2's bundled `pydantic.v1` compat
namespace. Both expose the same v1 API (`.dict()`/`.json()`/`.parse_obj()`,
`__fields_set__`) which is different from v2's (`.model_dump()`/
`.model_validate()`).

This module is the one place that duck-types across that split, so the rest
of `core` never has to import `pydantic.v1` — or any extra dependency — to
support it. It's the `_compat` shim `envelope.py`'s docstring anticipated.
"""

from __future__ import annotations

import json
from typing import Any


def is_v1_style(obj_or_cls: Any) -> bool:
    """True if `obj_or_cls` (an instance or a class) is a Pydantic-v1-style
    model rather than v2. Pydantic v2 models still expose a deprecated
    `.dict()` for migration convenience, so `model_dump` — v2-only — must be
    the gate that excludes them; `.dict()` alone isn't a reliable signal.
    """
    return not hasattr(obj_or_cls, "model_dump") and hasattr(obj_or_cls, "dict")


def dump_json_safe(instance: Any, *, exclude_unset: bool = False) -> Any:
    """JSON-safe `dict` for either a v1 or v2 model instance.

    v1's plain `.dict()` doesn't JSON-encode datetimes/enums/etc. the way
    v2's `mode="json"` does, so for v1 instances this round-trips through the
    model's own `.json()` encoder instead (which does).
    """
    if is_v1_style(instance):
        return json.loads(instance.json(exclude_unset=exclude_unset))
    return instance.model_dump(mode="json", exclude_unset=exclude_unset)


def validate(schema: Any, data: dict) -> Any:
    """Construct+validate `schema` from `data`, whichever Pydantic version
    `schema` belongs to."""
    if is_v1_style(schema):
        return schema.parse_obj(data)
    return schema.model_validate(data)
