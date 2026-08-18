"""Pluggable envelope serialization.

The default (`JSONSerializer`) just calls `StreamEnvelope.model_dump_json()`.
Swap it for msgpack, a custom encoder, etc. by implementing the `Serializer`
protocol and passing your instance to an adapter (e.g.
`to_sse_response(emitter, serializer=MyMsgpackSerializer())`).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .envelope import StreamEnvelope


@runtime_checkable
class Serializer(Protocol):
    """Anything with a `dumps(envelope) -> str` method can serve as a serializer."""

    def dumps(self, envelope: StreamEnvelope) -> str: ...


class JSONSerializer:
    """Default serializer: Pydantic v2's `.model_dump_json()`."""

    def dumps(self, envelope: StreamEnvelope) -> str:
        return envelope.to_json()


default_serializer = JSONSerializer()
