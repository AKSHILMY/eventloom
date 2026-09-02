"""Utilities for inspecting Pydantic model field types at runtime.

Used by :meth:`EventTypeRegistry.register_model` and :class:`ModelEmitter`
to auto-derive event types and merge strategies from schema definitions,
without requiring the developer to manually annotate every field.

Supports both Pydantic v1 (via ``pydantic.v1``) and Pydantic v2 models.

Pydantic v1 + ``from __future__ import annotations``
------------------------------------------------------
When ``from __future__ import annotations`` is active in the file where a
Pydantic v1 model is defined, Python stores all annotations as string
``ForwardRef`` objects instead of evaluating them eagerly.  Pydantic v1's
``field.outer_type_`` inherits this raw string in some circumstances, making
``typing.get_origin()`` return ``None`` instead of ``list``.

The functions here avoid this pitfall for v1 by using Pydantic v1's own
resolved field metadata instead of raw annotations:

* ``field.shape == SHAPE_LIST`` — reliable list detection, unaffected by
  ``ForwardRef``.
* ``field.type_`` — the *inner* type of a list / optional (already resolved
  by Pydantic v1's validator at model-creation time).
"""

from __future__ import annotations

import json
import types as _types
from typing import Any, Union, get_args, get_origin

from . import _compat

# ---------------------------------------------------------------------------
# Pydantic v1 shape constants — lazy-loaded so the main package doesn't
# require a real ``pydantic.v1`` install at module load time.
# ---------------------------------------------------------------------------

_V1_SHAPES: dict[str, int] | None = None


def _v1_shapes() -> dict[str, int]:
    """Return a mapping of Pydantic v1 shape-name → constant value."""
    global _V1_SHAPES
    if _V1_SHAPES is None:
        try:
            from pydantic.v1 import fields as _v1f  # type: ignore[import]
            _V1_SHAPES = {
                "list":      _v1f.SHAPE_LIST,        # 2
                "set":       _v1f.SHAPE_SET,         # 3
                "frozenset": _v1f.SHAPE_FROZENSET,   # 8
                "tuple":     _v1f.SHAPE_TUPLE,       # 5
                "sequence":  _v1f.SHAPE_SEQUENCE,    # 7
            }
        except Exception:
            # Hard-code the stable values from pydantic v1's source if the
            # import fails (e.g. when pydantic v2 does not bundle pydantic.v1).
            _V1_SHAPES = {"list": 2, "set": 3, "frozenset": 8, "tuple": 5, "sequence": 7}
    return _V1_SHAPES


def _v1_collection_shapes() -> frozenset[int]:
    """Return the set of v1 shape values that represent collection types
    (list, set, frozenset, tuple, sequence) — each may hold model item types
    that should be emitted as individual append events."""
    s = _v1_shapes()
    return frozenset(s.values())


# ---------------------------------------------------------------------------
# v2 annotation helpers
# ---------------------------------------------------------------------------

# Python built-in collection origin types that should be treated as
# sequence-of-items for the purpose of append-event detection.
_SEQUENCE_ORIGINS: frozenset[type] = frozenset({list, set, frozenset, tuple})


def _unwrap_optional(annotation: Any) -> Any:
    """Strip ``Optional[T]`` / ``T | None`` → ``T``.

    Handles both:
    * ``typing.Optional[T]`` / ``typing.Union[T, None]`` — origin is
      ``typing.Union``.
    * Python 3.10+ ``T | None`` syntax — produces ``types.UnionType``, whose
      ``get_origin()`` is ``types.UnionType`` (not ``typing.Union``), so we
      need a separate ``isinstance`` check.
    """
    origin = get_origin(annotation)
    if origin is Union:
        inner = [a for a in get_args(annotation) if a is not type(None)]
        if len(inner) == 1:
            return inner[0]
    # Python 3.10+ ``X | Y`` syntax
    if hasattr(_types, "UnionType") and isinstance(annotation, _types.UnionType):
        inner = [a for a in get_args(annotation) if a is not type(None)]
        if len(inner) == 1:
            return inner[0]
    return annotation


def is_list_annotation(annotation: Any) -> bool:
    """True if *annotation* (after unwrapping ``Optional``) is a sequence-like
    collection type (``list``, ``set``, ``frozenset``, ``tuple``).

    Pydantic v2 already strips ``Annotated[...]`` wrappers before storing
    ``FieldInfo.annotation``, so we never need to unwrap those here.

    Only safe for Pydantic v2 annotations.  For v1 models use
    :func:`get_list_field_item_types` which consults ``field.shape`` instead.
    """
    return get_origin(_unwrap_optional(annotation)) in _SEQUENCE_ORIGINS


def get_list_item_type(annotation: Any) -> Any | None:
    """Return the item type ``T`` from ``Collection[T]`` (list / set / frozenset /
    tuple), or ``None`` if the annotation is not a sequence type.

    For ``tuple[T, ...]`` this returns ``T`` (the element type, not the length
    specifier).  For fixed-length tuples like ``tuple[A, B]`` it returns ``A``
    — a simplification sufficient for append-event routing.

    Only safe for Pydantic v2 annotations.  For v1 models use
    :func:`get_list_field_item_types` which consults ``field.type_`` instead.
    """
    inner = _unwrap_optional(annotation)
    if get_origin(inner) in _SEQUENCE_ORIGINS:
        args = get_args(inner)
        # tuple[T, ...] → T; tuple[A, B] → A; others: first arg
        return args[0] if args else None
    return None


# ---------------------------------------------------------------------------
# Unified field-type inspection (v1 + v2)
# ---------------------------------------------------------------------------


def is_model_type(tp: Any) -> bool:
    """True if *tp* is a Pydantic BaseModel subclass (v1 or v2).

    Uses duck-typing (presence of ``model_fields`` or ``__fields__``) rather
    than importing a specific base class, so it works regardless of which
    Pydantic version is in use.
    """
    if not isinstance(tp, type):
        return False
    return hasattr(tp, "model_fields") or hasattr(tp, "__fields__")


def get_list_field_item_types(model_cls: Any) -> dict[str, Any]:
    """Return ``{field_name: item_type}`` for every list field in *model_cls*.

    For Pydantic v1 models this uses ``field.shape`` and ``field.type_``
    (immune to ``ForwardRef`` / ``from __future__ import annotations``).
    For Pydantic v2 models this inspects ``model_fields`` annotations.

    Only list fields whose item type is a Pydantic model class are included —
    primitive lists (``list[str]``, ``list[int]``, …) are intentionally
    excluded because they stream better as atomic scalar ``merge`` values.
    """
    if _compat.is_v1_style(model_cls):
        collection_shapes = _v1_collection_shapes()
        result: dict[str, Any] = {}
        for name, field in model_cls.__fields__.items():
            if getattr(field, "shape", None) in collection_shapes:
                item_type = getattr(field, "type_", None)
                if item_type is not None and is_model_type(item_type):
                    result[name] = item_type
        return result

    # Pydantic v2 path
    result = {}
    for name, info in model_cls.model_fields.items():
        annotation = info.annotation
        if is_list_annotation(annotation):
            item_type = get_list_item_type(annotation)
            if item_type is not None and is_model_type(item_type):
                result[name] = item_type
    return result


def get_model_field_annotations(model_cls: Any) -> dict[str, Any]:
    """Return ``{field_name: annotation}`` for every field in *model_cls*.

    For v2 models this is straightforward.  For v1 models the value is the
    resolved ``outer_type_`` which *may* be a ``ForwardRef`` when
    ``from __future__ import annotations`` is in effect — callers that only
    need to know about list vs scalar fields should prefer
    :func:`get_list_field_item_types` instead.
    """
    if _compat.is_v1_style(model_cls):
        return {
            name: field.outer_type_
            for name, field in model_cls.__fields__.items()
        }
    return {
        name: info.annotation
        for name, info in model_cls.model_fields.items()
    }


# ---------------------------------------------------------------------------
# Instance helpers
# ---------------------------------------------------------------------------


def get_fields_set(instance: Any) -> frozenset[str]:
    """Return the set of field names explicitly set on *instance*.

    Uses ``model_fields_set`` (v2) or ``__fields_set__`` (v1).
    """
    if _compat.is_v1_style(instance):
        return frozenset(instance.__fields_set__)
    return frozenset(instance.model_fields_set)


def make_delta_instance(model_cls: Any, delta: dict[str, Any]) -> Any:
    """Create a model instance carrying *only* the fields in *delta* as 'set'.

    Uses ``model_construct``/``construct`` (no validation) so that required
    fields not present in *delta* do not cause a ``ValidationError``.  The
    ``_fields_set`` / ``__fields_set__`` is set to exactly ``delta.keys()``
    so that ``model_dump(exclude_unset=True)`` / ``dict(exclude_unset=True)``
    only serializes the delta fields — critical for the ``merge`` strategy,
    where :meth:`StreamEnvelope.to_json` calls ``model_dump(exclude_unset=True)``
    to send only the changed portion to the frontend.
    """
    fields_set = set(delta.keys())
    if _compat.is_v1_style(model_cls):
        # Pydantic v1's construct() takes _fields_set (single underscore).
        # Using __fields_set (double underscore) instead would pass it via
        # **values, leaking it into __dict__ and contaminating __fields_set__
        # with the spurious key "__fields_set".
        return model_cls.construct(_fields_set=fields_set, **delta)
    return model_cls.model_construct(_fields_set=fields_set, **delta)


def serialize_for_comparison(value: Any) -> Any:
    """Return a JSON-safe, equality-comparable form of *value*.

    Pydantic model instances are converted to their dict form so that value
    equality rather than object identity is used for change detection.
    """
    if _compat.is_v1_style(value):
        return json.loads(value.json())
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value
