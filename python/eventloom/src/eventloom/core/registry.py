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

    def __contains__(self, type_name: str) -> bool:
        return type_name in self._specs

    def __iter__(self):
        return iter(self._specs.values())

    def __len__(self) -> int:
        return len(self._specs)
