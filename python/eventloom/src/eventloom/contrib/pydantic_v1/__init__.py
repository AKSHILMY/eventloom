"""
eventloom.contrib.pydantic_v1 — Partial object streaming for Pydantic v1
models: `instructor`'s replacement for schemas that predate Pydantic v2
(`instructor` itself doesn't support Pydantic v1).

Works against either a genuine standalone `pydantic<2` install, or — the
common case inside `eventloom`, whose core requires `pydantic>=2,<3` — the
`pydantic.v1` compat namespace Pydantic v2 bundles for exactly this
migration scenario. See `_pydantic1.py` for the import shim; callers of this
package never need to think about which one they're on.

Requires the `pydantic-v1` extra for the provider clients:
`pip install "eventloom[pydantic-v1]"` (pulls in `openai`/`anthropic`).

Usage:
    from eventloom.contrib.pydantic_v1 import BaseModel, stream_new_list_items
    from eventloom.contrib.pydantic_v1.providers.openai import OpenAIStreamClient

    class MyModel(BaseModel):
        title: str
        items: list[Item] = []

    client = OpenAIStreamClient()  # reads OPENAI_API_KEY from the environment
    async for partial_obj in client.stream(model="gpt-4o-mini", response_model=MyModel, messages=[...]):
        print(partial_obj)  # MyModel with progressively more fields filled

    # Non-streaming, single validated result (mirrors instructor's `.create()`):
    result = await client.create(model="gpt-4o-mini", response_model=MyModel, messages=[...])

    # `create_iterable()`-equivalent for a growing list field:
    async for item in stream_new_list_items(
        client.stream(model="gpt-4o-mini", response_model=MyModel, messages=[...]),
        get_list=lambda p: p.items,
    ):
        print(item)  # each Item, exactly once, as soon as it's complete

Partial[MyModel] is a compatibility shim — it simply returns MyModel,
so existing code written for instructor's Partial[Model] keeps working.
"""

from ._pydantic1 import BaseModel
from .errors import PartialStreamValidationError
from .partial import build_partial_model
from .stream import stream_items, stream_model
from .streaming import stream_new_list_items


class _PartialMeta(type):
    def __getitem__(cls, item):
        return item  # Partial[Model] → Model


class Partial(metaclass=_PartialMeta):
    """Drop-in alias: Partial[MyModel] == MyModel."""

    pass


__all__ = [
    "BaseModel",
    "Partial",
    "PartialStreamValidationError",
    "build_partial_model",
    "stream_items",
    "stream_model",
    "stream_new_list_items",
]
