"""EventEmitter — framework-agnostic event production.

`EventEmitter` knows nothing about HTTP, SSE, or FastAPI. It validates data
against its declared schema, wraps it in a `StreamEnvelope`, and makes it
available to be consumed via `events()`. This is what makes multi-framework
support cheap: a Flask adapter and a FastAPI adapter both just differ in
*how they drain the emitter into a response*, not in event logic.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, AsyncIterator

import anyio
from pydantic import BaseModel

from . import _compat
from .envelope import STREAM_ERROR_TYPE, StreamEnvelope, StreamError
from .registry import EventTypeRegistry


class EmitterClosedError(RuntimeError):
    """Raised by `emit()` after `close()`/`aclose()` has been called."""


class EventEmitter:
    """Produces `StreamEnvelope` objects and buffers them for an adapter to drain.

    Not tied to any particular concurrency library beyond the standard
    `async`/`await` protocol — internally uses an `anyio` memory stream so it
    works the same under asyncio or trio.
    """

    def __init__(self, registry: EventTypeRegistry, group_id: str | None = None) -> None:
        self.registry = registry
        self.group_id = group_id
        self._seq_counters: dict[str, int] = defaultdict(int)
        self._send, self._receive = anyio.create_memory_object_stream[StreamEnvelope](
            max_buffer_size=math.inf
        )
        self._closed = False

    async def emit(
        self,
        type_name: str,
        data: BaseModel | dict[str, Any],
        id: str | None = None,
        done: bool = False,
    ) -> StreamEnvelope:
        """Validate `data` against the schema registered for `type_name`, wrap it
        in a `StreamEnvelope`, and enqueue it for the adapter to send.

        `data` may be an instance of the registered schema, or a plain dict
        (validated via the schema's `model_validate` — or, for a schema
        registered from `eventloom.contrib.pydantic_v1`, its v1 equivalent
        `parse_obj`, via `_compat.validate`). Raises
        `eventloom.core.registry.UnknownEventTypeError` if `type_name` was
        never registered, or `pydantic.ValidationError` if `data` doesn't
        match the schema.
        """
        if self._closed:
            raise EmitterClosedError(f"Cannot emit {type_name!r}: this EventEmitter is closed.")

        spec = self.registry.get(type_name)
        if isinstance(data, spec.schema):
            payload = data
        elif isinstance(data, dict):
            payload = _compat.validate(spec.schema, data)
        else:
            raise TypeError(
                f"emit({type_name!r}, ...) expected a {spec.schema.__name__} instance or dict, "
                f"got {type(data).__name__}."
            )

        envelope_id = id if id is not None else type_name
        seq = self._seq_counters[envelope_id]
        self._seq_counters[envelope_id] += 1

        envelope = StreamEnvelope(
            type=type_name,
            id=envelope_id,
            seq=seq,
            data=payload,
            strategy=spec.strategy,
            done=done,
        )
        await self._send.send(envelope)
        return envelope

    async def emit_error(self, message: str, code: str | None = None, id: str = STREAM_ERROR_TYPE) -> StreamEnvelope:
        """Emit the built-in `__stream_error__` event type.

        Bypasses the registry (error events aren't developer-registered) so it
        works even mid-stream after something has already gone wrong.
        Frontend packages special-case this type and route it to an error
        fallback rather than the component registry.
        """
        envelope = StreamEnvelope(
            type=STREAM_ERROR_TYPE,
            id=id,
            seq=self._seq_counters[id],
            data=StreamError(message=message, code=code),
            strategy="replace",
            done=True,
        )
        self._seq_counters[id] += 1
        if not self._closed:
            await self._send.send(envelope)
        return envelope

    def close(self) -> None:
        """Signal that no more events will be emitted; `events()` will stop iterating
        once already-buffered envelopes are drained."""
        if not self._closed:
            self._closed = True
            self._send.close()

    async def aclose(self) -> None:
        self.close()

    async def events(self) -> AsyncIterator[StreamEnvelope]:
        """The adapter consumes this to know what to send. Iteration ends when
        `close()`/`aclose()` has been called and the buffer is drained."""
        async with self._receive:
            async for envelope in self._receive:
                yield envelope  # type: ignore[misc]

    async def __aenter__(self) -> "EventEmitter":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.close()
