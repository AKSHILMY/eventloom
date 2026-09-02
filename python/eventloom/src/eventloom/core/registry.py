"""EventTypeRegistry — the central place a developer declares every event type
their backend emits.

Zero framework dependencies. A registry is typically defined once in a shared
module (e.g. ``myapp/events.py``) and imported by every route/task that emits
events, and also used as the input to the optional codegen bridge (plan
section 5.3) that generates matching TypeScript types.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Type

from pydantic import BaseModel

from .envelope import MergeStrategy
from . import schema_utils as _su


class UnknownEventTypeError(KeyError):
    """Raised by `EventTypeRegistry.get()` for a type name that was never registered."""

    def __init__(self, type_name: str) -> None:
        super().__init__(type_name)
        self.type_name = type_name

    def __str__(self) -> str:  # pragma: no cover - trivial
        return (
            f"Unknown event type {self.type_name!r}. "
            "Register it first with `registry.register(...)`."
        )


class DuplicateEventTypeError(ValueError):
    """Raised when a type name is registered twice with a different schema."""


@dataclass(frozen=True)
class EventTypeSpec:
    """The registered configuration for one event type."""

    type_name: str
    schema: Type[BaseModel]
    strategy: MergeStrategy


class EventTypeRegistry:
    """Maps an event type name to its Pydantic payload schema and default merge
    strategy.

    Registering the same type name twice with an identical schema/strategy is
    a no-op (idempotent — convenient when a shared events module gets
    imported from multiple entry points). Registering it twice with a
    *different* schema or strategy raises, since that's almost always a bug.
    """

    def __init__(self) -> None:
        self._specs: dict[str, EventTypeSpec] = {}

    def register(
        self,
        type_name: str,
        schema: Type[BaseModel],
        strategy: MergeStrategy = "replace",
    ) -> None:
        existing = self._specs.get(type_name)
        if existing is not None:
            if existing.schema is schema and existing.strategy == strategy:
                return
            raise DuplicateEventTypeError(
                f"Event type {type_name!r} is already registered with "
                f"schema={existing.schema.__name__!r} strategy={existing.strategy!r}; "
                f"got schema={schema.__name__!r} strategy={strategy!r}."
            )
        self._specs[type_name] = EventTypeSpec(type_name=type_name, schema=schema, strategy=strategy)

    def get(self, type_name: str) -> EventTypeSpec:
        try:
            return self._specs[type_name]
        except KeyError:
            raise UnknownEventTypeError(type_name) from None

    def register_model(
        self,
        prefix: str,
        schema: Type[BaseModel],
    ) -> None:
        """Auto-register event types derived from a Pydantic model schema.

        Inspects *schema*'s fields and registers:

        * ``prefix`` with ``strategy="merge"`` — receives scalar and nested
          model fields as partial deltas.
        * ``"{prefix}.{field_name}"`` with ``strategy="append"`` for each
          list field whose item type is itself a Pydantic model — receives
          one event per completed item.

        List fields with primitive item types (``list[str]``, ``list[int]``,
        …) are *not* given a separate event type; they are included in the
        parent ``merge`` stream as atomic scalar values.

        This is designed for use with :class:`eventloom.core.ModelEmitter`,
        which automatically emits the correct events during partial streaming::

            registry = EventTypeRegistry()
            registry.register_model("profile", UserProfile)

            async with ModelEmitter(emitter, "profile", id="u-1") as me:
                async for partial in instructor.create_partial(UserProfile, ...):
                    await me.emit_partial(partial)

        Parameters
        ----------
        prefix:
            The event-type name for the root merge stream (e.g.
            ``"company.profile"``).  Must not already be registered with a
            *different* schema or strategy (duplicate-idempotent otherwise).
        schema:
            A Pydantic ``BaseModel`` subclass (v1 or v2).
        """
        # Register the parent merge event for all scalar / non-list fields.
        self.register(prefix, schema, strategy="merge")

        # Register separate append events for list fields with model item types.
        # Uses get_list_field_item_types() which is immune to ForwardRef issues
        # caused by ``from __future__ import annotations`` in v1 model files.
        for field_name, item_type in _su.get_list_field_item_types(schema).items():
            self.register(f"{prefix}.{field_name}", item_type, strategy="append")

    def __contains__(self, type_name: str) -> bool:
        return type_name in self._specs

    def __iter__(self):
        return iter(self._specs.values())

    def __len__(self) -> int:
        return len(self._specs)
