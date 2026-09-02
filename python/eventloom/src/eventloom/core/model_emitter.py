"""ModelEmitter — zero-boilerplate partial-model streaming.

Given a Pydantic model class and a registered event prefix,
:class:`ModelEmitter` inspects the schema, tracks state between partial chunks
(e.g. from ``instructor.create_partial()``), and emits the minimum set of
events needed to keep the frontend up to date — without the developer having
to maintain a ``sent`` dict or manually figure out which fields changed.

Strategy auto-inference
-----------------------
- **Scalar / nested-model fields** → batched into a single ``merge`` event
  carrying only the fields that changed since the last chunk (``{prefix}``).
- **List fields whose item type is itself a Pydantic model** → one ``append``
  event per new item, with event type ``"{prefix}.{field_name}"`` and
  envelope id ``"{base_id}.{field_name}"``.
- **List fields with primitive item types** (``list[str]``, ``list[int]``,
  …) → treated as atomic scalar values and included in the merge delta (the
  whole list replaces itself on the frontend).

Typical usage::

    registry = EventTypeRegistry()
    registry.register_model("example", Example)  # auto-registers all sub-types

    async with ModelEmitter(emitter, "example", id="ex-1") as me:
        async for partial in instructor.create_partial(Example, ...):
            await me.emit_partial(partial)
        # done=True emitted automatically on context-manager exit

Or without a context manager::

    me = ModelEmitter(emitter, "example", id="ex-1")
    async for partial in stream:
        await me.emit_partial(partial)
    await me.done()

Note: :class:`ModelEmitter` does **not** close the underlying
:class:`EventEmitter` on exit — it only sends the ``done=True`` marker.
The caller retains ownership of the emitter's lifecycle.
"""

from __future__ import annotations

from typing import Any

from . import schema_utils as _su
from ._compat import is_v1_style
from .emitter import EventEmitter


class ModelEmitter:
    """Stateful wrapper around :class:`EventEmitter` for partial model streaming.

    Create one :class:`ModelEmitter` per logical streaming entity (e.g. one
    per company profile). Reuse it across all partial chunks for that entity.

    Parameters
    ----------
    emitter:
        The underlying :class:`EventEmitter` to emit events through.
    prefix:
        The event-type prefix used when registering the model with
        :meth:`EventTypeRegistry.register_model`.  Scalar merge events are
        emitted as ``prefix``; list append events as ``"{prefix}.{field}"``.
    id:
        Default envelope ``id`` for merge events.  List append events use
        ``"{id}.{field_name}"``.  Defaults to *prefix* if omitted.
    model_cls:
        Optional explicit model class.  When omitted, it is inferred from
        the first :meth:`emit_partial` call.
    """

    def __init__(
        self,
        emitter: EventEmitter,
        prefix: str,
        *,
        id: str | None = None,
        model_cls: type | None = None,
    ) -> None:
        self._emitter = emitter
        self._prefix = prefix
        self._default_id = id or prefix
        self._model_cls = model_cls

        # Per-(id, field_name) watermark: how many list items were already
        # emitted.  Only new items (value[old_count:]) are forwarded.
        self._list_counts: dict[tuple[str, str], int] = {}

        # Per-(id, field_name) last emitted value in JSON-safe form.
        # Used for scalar change detection — avoids re-sending unchanged fields.
        self._last_scalar: dict[tuple[str, str], Any] = {}

        # Track whether done() was already called for a given id.
        self._done_ids: set[str] = set()

        # Holds the most-recent last item for each (effective_id, field_name).
        # Items are NOT emitted when they are the last in the list because the
        # LLM is still filling in their content.  They are flushed either when
        # a new item appears after them (making them no longer last) or in
        # done() when the stream ends.  Value is (list_event_type, list_id, item).
        self._pending_last: dict[tuple[str, str], tuple[str, str, Any]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def emit_partial(
        self,
        partial: Any,
        *,
        id: str | None = None,
    ) -> None:
        """Diff *partial* against last emitted state and forward only the delta.

        Parameters
        ----------
        partial:
            A Pydantic model instance (v1 or v2) with some fields set.
            Typically the output of ``instructor.create_partial()``.
        id:
            Override the default envelope ``id`` for this call.
        """
        effective_id = id or self._default_id

        # Infer model class from first call when not given at construction.
        if self._model_cls is None:
            self._model_cls = type(partial)

        # Build the list-field map once per model class.  This is v1/v2-safe
        # and immune to ForwardRef issues from `from __future__ import annotations`.
        model_list_fields = _su.get_list_field_item_types(self._model_cls)

        fields_set = _su.get_fields_set(partial)
        scalar_delta: dict[str, Any] = {}

        for field_name in fields_set:
            value = getattr(partial, field_name)

            if field_name in model_list_fields:
                # List of model objects → one append event per new item
                await self._emit_new_list_items(
                    field_name=field_name,
                    value=value,
                    effective_id=effective_id,
                )
            else:
                # Scalar, nested model, or primitive list → merge delta
                self._collect_scalar_change(
                    field_name=field_name,
                    value=value,
                    effective_id=effective_id,
                    delta=scalar_delta,
                )

        if scalar_delta:
            delta_instance = _su.make_delta_instance(self._model_cls, scalar_delta)
            await self._emitter.emit(self._prefix, delta_instance, id=effective_id)

    async def done(self, *, id: str | None = None) -> None:
        """Mark the stream for *id* as complete (sends an empty merge with ``done=True``).

        Calling :meth:`done` more than once for the same *id* is a no-op.
        """
        effective_id = id or self._default_id
        if effective_id in self._done_ids:
            return
        self._done_ids.add(effective_id)

        # Flush any list item that was held pending (was last when the stream
        # ended — never got a successor to trigger its emission).
        for key in [k for k in self._pending_last if k[0] == effective_id]:
            list_event_type, list_id, item = self._pending_last.pop(key)
            await self._emitter.emit(list_event_type, item, id=list_id)

        # Resolve schema from the registry if emit_partial was never called.
        model_cls = self._model_cls
        if model_cls is None:
            spec = self._emitter.registry.get(self._prefix)
            model_cls = spec.schema

        empty = _su.make_delta_instance(model_cls, {})
        await self._emitter.emit(self._prefix, empty, id=effective_id, done=True)

    # ------------------------------------------------------------------
    # Async context manager — sends done=True on exit, does NOT close the
    # underlying emitter (caller retains ownership).
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "ModelEmitter":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.done()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _emit_new_list_items(
        self,
        *,
        field_name: str,
        value: Any,
        effective_id: str,
    ) -> None:
        """Emit one append event per collection item that is new since the last chunk.

        Accepts any iterable collection (list, set, frozenset, tuple) — the
        value is normalised to a list so that watermarking (slice by old_count)
        works uniformly across all collection types.  Sets and frozensets do
        not guarantee stable iteration order across Python runs, but within a
        single partial-streaming session the instructor stream never removes
        items — it only appends — so the watermark is still safe.
        """
        if not isinstance(value, (list, set, frozenset, tuple)):
            return

        # Normalise to list for stable slicing.
        items: list[Any] = list(value)

        list_event_type = f"{self._prefix}.{field_name}"
        # Skip silently if the list event type was never registered — the
        # developer may have called register() manually and omitted this
        # sub-type.  We avoid an UnknownEventTypeError so partial-model
        # streaming still works for the scalar fields.
        if list_event_type not in self._emitter.registry:
            return

        list_id = f"{effective_id}.{field_name}"
        count_key = (effective_id, field_name)
        old_count = self._list_counts.get(count_key, 0)

        # Emit all items that are no longer the last in the list — they are
        # "complete" because a newer item has appeared after them.  The last
        # item is held pending: the LLM may still be filling in its content.
        complete_up_to = len(items) - 1 if items else 0
        complete_up_to = max(old_count, complete_up_to)
        for item in items[old_count:complete_up_to]:
            await self._emitter.emit(list_event_type, item, id=list_id)

        # Store the current last item so done() can flush it when the stream ends.
        if items:
            self._pending_last[count_key] = (list_event_type, list_id, items[-1])

        self._list_counts[count_key] = complete_up_to

    def _collect_scalar_change(
        self,
        *,
        field_name: str,
        value: Any,
        effective_id: str,
        delta: dict[str, Any],
    ) -> None:
        """Add *field_name* → *value* to *delta* only if the value changed."""
        serialized = _su.serialize_for_comparison(value)
        key = (effective_id, field_name)
        if self._last_scalar.get(key) != serialized:
            delta[field_name] = value
            self._last_scalar[key] = serialized
