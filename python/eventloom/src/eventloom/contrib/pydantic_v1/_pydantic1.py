"""Single place every `eventloom.contrib.pydantic_v1` module imports
Pydantic v1's `BaseModel` and field-shape constants from, so the rest of the
package doesn't care whether it's running against:

- Pydantic v2's bundled `pydantic.v1` compat namespace (the common case:
  `eventloom`'s core requires `pydantic>=2,<3`, and you can't pip-install a
  genuine `pydantic<2` alongside it in the same environment) — or
- a genuine standalone `pydantic<2` install (e.g. an older codebase this
  module was ported from, which never installed Pydantic v2 at all).

Both expose an identical v1 API (`BaseModel.construct()`, `.dict()`,
`.json()`, `.parse_obj()`, `ModelField.shape`/`.type_`, the `SHAPE_*`
constants), so everything downstream is written once against that API.
"""

try:
    from pydantic.v1 import BaseModel, ValidationError
    from pydantic.v1.fields import (
        SHAPE_DICT,
        SHAPE_LIST,
        SHAPE_SET,
        SHAPE_SINGLETON,
        SHAPE_TUPLE,
        SHAPE_TUPLE_ELLIPSIS,
    )
except ImportError:  # genuine standalone pydantic<2
    from pydantic import BaseModel, ValidationError  # type: ignore[no-redef]
    from pydantic.fields import (  # type: ignore[no-redef]
        SHAPE_DICT,
        SHAPE_LIST,
        SHAPE_SET,
        SHAPE_SINGLETON,
        SHAPE_TUPLE,
        SHAPE_TUPLE_ELLIPSIS,
    )

__all__ = [
    "BaseModel",
    "ValidationError",
    "SHAPE_DICT",
    "SHAPE_LIST",
    "SHAPE_SET",
    "SHAPE_SINGLETON",
    "SHAPE_TUPLE",
    "SHAPE_TUPLE_ELLIPSIS",
]
