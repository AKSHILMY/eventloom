"""
Build partial Pydantic v1 model instances from raw dictionaries.

Uses Model.construct() (Pydantic v1 equivalent of v2's model_construct()) which
bypasses validation. This lets partially-filled JSON populate a model without
raising ValidationError on missing required fields.

Supported field shapes:
- Scalar (str, int, float, bool): passed through as-is
- Enum: passed through as raw string (construct() skips coercion)
- Optional[X]: None passthrough; non-None processed as X
- Nested BaseModel (SHAPE_SINGLETON): recursively built
- List[BaseModel] (SHAPE_LIST): each element recursively built
- Dict[str, BaseModel] (SHAPE_DICT): each value recursively built
- Set[BaseModel] (SHAPE_SET): each element recursively built; falls back to a
  list if the built (unvalidated) elements aren't hashable
- Tuple[BaseModel, ...] / Tuple[A, B, ...] (SHAPE_TUPLE / SHAPE_TUPLE_ELLIPSIS):
  each element recursively built
- List[scalar], plain Dict, other shapes: passed through as-is
"""

from typing import Any, Dict, Type, TypeVar

from ._pydantic1 import (
    BaseModel,
    SHAPE_DICT,
    SHAPE_LIST,
    SHAPE_SET,
    SHAPE_SINGLETON,
    SHAPE_TUPLE,
    SHAPE_TUPLE_ELLIPSIS,
)

M = TypeVar("M", bound=BaseModel)

_SEQUENCE_SHAPES = (SHAPE_LIST, SHAPE_SET, SHAPE_TUPLE, SHAPE_TUPLE_ELLIPSIS)


def _is_base_model_type(tp: Any) -> bool:
    try:
        return isinstance(tp, type) and issubclass(tp, BaseModel)
    except TypeError:
        return False


def _build_sequence(inner_type: Any, raw_val: Any) -> list:
    """Recursively build each element of a list/set/tuple-shaped raw value.
    Always returns a list — callers apply shape-specific coercion (set/tuple)
    on top, since construct()-based partials may not yet be hashable/complete."""
    if not isinstance(raw_val, list):
        return raw_val
    return [build_partial_model(inner_type, v) if isinstance(v, dict) else v for v in raw_val]


def build_partial_model(model_cls: Type[M], data: Dict[str, Any]) -> M:
    """
    Build a partial instance of a Pydantic v1 model from a raw dict.

    Fields absent from `data` are omitted entirely (not set to None or default).
    Callers can use `getattr(obj, field_name, None)` for not-yet-streamed fields.

    Args:
        model_cls: A Pydantic v1 BaseModel subclass.
        data: Raw dict from partial JSON parsing.

    Returns:
        An instance of model_cls populated via construct() (no validation).
    """
    if not isinstance(data, dict):
        return model_cls.construct()

    field_values: Dict[str, Any] = {}

    for field_name, field in model_cls.__fields__.items():
        key = field.alias if field.has_alias else field_name

        if field_name in data:
            raw_val = data[field_name]
        elif key in data:
            raw_val = data[key]
        else:
            continue  # not yet streamed — skip

        if raw_val is None:
            field_values[field_name] = None
            continue

        inner_type = field.type_
        shape = field.shape

        if shape == SHAPE_SINGLETON and _is_base_model_type(inner_type):
            field_values[field_name] = (
                build_partial_model(inner_type, raw_val) if isinstance(raw_val, dict) else raw_val
            )
        elif shape == SHAPE_DICT and _is_base_model_type(inner_type):
            if isinstance(raw_val, dict):
                field_values[field_name] = {
                    k: build_partial_model(inner_type, v) if isinstance(v, dict) else v
                    for k, v in raw_val.items()
                }
            else:
                field_values[field_name] = raw_val
        elif shape in _SEQUENCE_SHAPES and _is_base_model_type(inner_type):
            items = _build_sequence(inner_type, raw_val)
            if shape == SHAPE_SET and isinstance(items, list):
                try:
                    field_values[field_name] = set(items)
                except TypeError:
                    # Partial (construct()-based) elements aren't guaranteed
                    # hashable — fall back to a list rather than fail the
                    # whole partial build over one not-yet-hashable field.
                    field_values[field_name] = items
            elif shape in (SHAPE_TUPLE, SHAPE_TUPLE_ELLIPSIS) and isinstance(items, list):
                field_values[field_name] = tuple(items)
            else:
                field_values[field_name] = items
        else:
            # Scalar, Enum, List[scalar], Dict[str, scalar] — pass through as-is
            field_values[field_name] = raw_val

    return model_cls.construct(**field_values)
