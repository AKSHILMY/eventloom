"""The wire protocol envelope.

This is the one artifact that both the Python and TypeScript packages must
agree on byte-for-byte (as JSON). See ``eventloom-project-plan.md`` section 2
for the frozen contract. Do not change field names or semantics without a
matching change on the TypeScript side (``@akshilmy/eventloom-core``'s
``StreamEnvelope`` type) — this is a breaking wire-format change.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from . import _compat

T = TypeVar("T")

MergeStrategy = Literal["replace", "merge", "append"]
"""How a new envelope's ``data`` combines with prior envelopes sharing the same ``id``.

- ``replace``: new data fully replaces old (discrete events).
- ``merge``: shallow-merge new fields into the existing object (partial objects
  streaming in, e.g. a profile being filled in field by field).
- ``append``: push into an array (e.g. streaming log lines, chat tokens).
"""


class StreamEnvelope(BaseModel, Generic[T]):
    """One JSON object per SSE ``data:`` line.

    ``type`` is the registry lookup key on the frontend. ``id`` groups events
    belonging to the same logical "thing" (e.g. all partials for one chart
    share an ``id``). ``seq`` is a monotonic sequence number within that
    ``id``, so the frontend can order/dedupe defensively even though SSE
    already guarantees in-order delivery per connection.
    """

    type: str = Field(..., description='Event type, e.g. "chart.data" — routes to a component.')
    id: str = Field(..., description="Groups events belonging to the same logical thing.")
    seq: int = Field(..., description="Monotonic sequence number within this id.")
    data: T = Field(..., description="Event-specific payload.")
    strategy: MergeStrategy = Field(
        default="replace",
        description="How this event combines with prior ones sharing `id`.",
    )
    done: bool = Field(default=False, description="True if this is the final event for this id.")
    ts: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO timestamp, for debugging/latency measurement.",
    )

    def to_json(self) -> str:
        """JSON serialization of the envelope.

        Targets Pydantic v2 (`.model_dump_json()`) for the envelope itself —
        `StreamEnvelope` is always v2, that never changes. `data`, however,
        may be a Pydantic-v1-style instance (from `eventloom.contrib.
        pydantic_v1`, see its docstring): the `_compat.is_v1_style()` branch
        below handles that case via version-neutral helpers, so v2's own
        `model_dump_json()`/`model_dump()` — which can't serialize a foreign
        non-v2 model sitting in an `Any`-typed field — is never asked to.

        For `strategy == "merge"`, `data` is dumped with `exclude_unset=True`
        so only the fields the emitter actually set are sent — otherwise
        Pydantic would fill every unset field with its default (usually
        `null`), and a frontend doing `{...existing, ...incoming}` would
        silently clobber fields a *previous* merge event already set. This
        only matters for `merge`: `replace` intentionally sends the full
        object (it's meant to be the complete authoritative state), and
        `append` payloads are normally fully-specified items anyway.
        """
        if _compat.is_v1_style(self.data):
            payload = self.model_dump(mode="json", exclude={"data"})
            payload["data"] = _compat.dump_json_safe(self.data, exclude_unset=(self.strategy == "merge"))
            return json.dumps(payload, separators=(",", ":"))
        if self.strategy == "merge" and isinstance(self.data, BaseModel):
            payload = self.model_dump(mode="json", exclude={"data"})
            payload["data"] = self.data.model_dump(mode="json", exclude_unset=True)
            return json.dumps(payload, separators=(",", ":"))
        return self.model_dump_json()

    def to_sse(self) -> str:
        """Render as a standard SSE ``data:`` line (including the trailing blank line)."""
        return f"data: {self.to_json()}\n\n"


class StreamError(BaseModel):
    """Payload for the built-in ``__stream_error__`` event type.

    Emitted by adapters when the underlying stream fails after the HTTP
    response has already started (so a normal error status code is no longer
    possible). Frontend packages special-case ``type == "__stream_error__"``
    and route it to an error fallback rather than the registry.
    """

    message: str
    code: str | None = None


STREAM_ERROR_TYPE = "__stream_error__"
