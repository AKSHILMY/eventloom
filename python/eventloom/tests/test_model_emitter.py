"""Tests for ModelEmitter and EventTypeRegistry.register_model.

Covers:
- register_model: auto-registration of merge + append event types
- ModelEmitter.emit_partial: scalar delta detection, list append detection
- ModelEmitter.done: done signal with empty merge delta
- Context manager usage (done sent on exit)
- Pydantic v1 compat
- Edge cases: primitive lists, nested models, unchanged fields
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

import pytest
from pydantic import BaseModel

from eventloom import (
    EventEmitter,
    EventTypeRegistry,
    ModelEmitter,
    UnknownEventTypeError,
)


# ---------------------------------------------------------------------------
# Test schemas
# ---------------------------------------------------------------------------


class InterestSchema(BaseModel):
    name: str
    score: str  # "low" | "medium" | "high"


class ExampleModel(BaseModel):
    name: str
    title: str
    description: str
    interests: List[InterestSchema]
    tags: List[str]  # primitive list — stays in merge stream


class SimpleModel(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = None


# ---------------------------------------------------------------------------
# register_model
# ---------------------------------------------------------------------------


def test_register_model_creates_merge_event_for_parent():
    registry = EventTypeRegistry()
    registry.register_model("example", ExampleModel)

    spec = registry.get("example")
    assert spec.schema is ExampleModel
    assert spec.strategy == "merge"


def test_register_model_creates_append_event_for_model_list_fields():
    registry = EventTypeRegistry()
    registry.register_model("example", ExampleModel)

    # interests is List[InterestSchema] — gets its own append event
    spec = registry.get("example.interests")
    assert spec.schema is InterestSchema
    assert spec.strategy == "append"


def test_register_model_does_not_create_event_for_primitive_list_fields():
    registry = EventTypeRegistry()
    registry.register_model("example", ExampleModel)

    # tags is List[str] — no separate event, handled in merge stream
    assert "example.tags" not in registry


def test_register_model_is_idempotent_when_called_twice_with_same_args():
    registry = EventTypeRegistry()
    registry.register_model("example", ExampleModel)
    registry.register_model("example", ExampleModel)  # should not raise


def test_register_model_raises_on_conflicting_registration():
    from eventloom import DuplicateEventTypeError

    registry = EventTypeRegistry()
    registry.register_model("example", ExampleModel)
    # Registering the same prefix with a different schema raises
    with pytest.raises(DuplicateEventTypeError):
        registry.register_model("example", SimpleModel)


# ---------------------------------------------------------------------------
# ModelEmitter — scalar merge delta
# ---------------------------------------------------------------------------


@pytest.fixture()
def example_registry() -> EventTypeRegistry:
    reg = EventTypeRegistry()
    reg.register_model("example", ExampleModel)
    return reg


async def test_emit_partial_emits_scalar_merge_event(example_registry):
    emitter = EventEmitter(example_registry)
    me = ModelEmitter(emitter, "example", id="ex-1")

    # Partial with only name set
    partial = ExampleModel.model_construct(name="Nimbus", _fields_set={"name"})
    await me.emit_partial(partial)
    emitter.close()

    events = [e async for e in emitter.events()]
    assert len(events) == 1
    assert events[0].type == "example"
    assert events[0].strategy == "merge"
    assert events[0].id == "ex-1"


async def test_emit_partial_only_sends_changed_scalar_fields(example_registry):
    emitter = EventEmitter(example_registry)
    me = ModelEmitter(emitter, "example", id="ex-1")

    # Chunk 1: only name
    p1 = ExampleModel.model_construct(name="Nimbus", _fields_set={"name"})
    await me.emit_partial(p1)

    # Chunk 2: name unchanged, title added
    p2 = ExampleModel.model_construct(name="Nimbus", title="AI Infra", _fields_set={"name", "title"})
    await me.emit_partial(p2)

    emitter.close()
    events = [e async for e in emitter.events()]

    # Chunk 1 → only name
    data1 = events[0].data.model_dump(exclude_unset=True)
    assert data1 == {"name": "Nimbus"}

    # Chunk 2 → only title (name unchanged)
    data2 = events[1].data.model_dump(exclude_unset=True)
    assert data2 == {"title": "AI Infra"}


async def test_emit_partial_emits_nothing_when_no_fields_changed(example_registry):
    emitter = EventEmitter(example_registry)
    me = ModelEmitter(emitter, "example", id="ex-1")

    p = ExampleModel.model_construct(name="Nimbus", _fields_set={"name"})
    await me.emit_partial(p)
    await me.emit_partial(p)  # same fields, same values — no delta

    emitter.close()
    events = [e async for e in emitter.events()]
    assert len(events) == 1  # only one merge event, not two


# ---------------------------------------------------------------------------
# ModelEmitter — list append events
# ---------------------------------------------------------------------------


async def test_emit_partial_emits_append_event_for_each_new_list_item(example_registry):
    emitter = EventEmitter(example_registry)
    me = ModelEmitter(emitter, "example", id="ex-1")

    interest1 = InterestSchema(name="ML", score="high")
    p1 = ExampleModel.model_construct(
        interests=[interest1],
        _fields_set={"interests"},
    )
    await me.emit_partial(p1)

    interest2 = InterestSchema(name="DL", score="medium")
    p2 = ExampleModel.model_construct(
        interests=[interest1, interest2],
        _fields_set={"interests"},
    )
    await me.emit_partial(p2)
    # done() flushes the last pending item (DL, which had no successor).
    await me.done()

    emitter.close()
    events = [e async for e in emitter.events()]

    append_events = [e for e in events if e.type == "example.interests"]
    assert len(append_events) == 2
    assert append_events[0].data.name == "ML"
    assert append_events[1].data.name == "DL"
    # Both share the same list id
    assert all(e.id == "ex-1.interests" for e in append_events)
    assert all(e.strategy == "append" for e in append_events)


async def test_emit_partial_does_not_re_emit_existing_list_items(example_registry):
    emitter = EventEmitter(example_registry)
    me = ModelEmitter(emitter, "example", id="ex-1")

    interest = InterestSchema(name="ML", score="high")
    p = ExampleModel.model_construct(interests=[interest], _fields_set={"interests"})

    await me.emit_partial(p)
    await me.emit_partial(p)  # same list — no new items
    # done() flushes the single pending item.
    await me.done()

    emitter.close()
    events = [e async for e in emitter.events()]
    append_events = [e for e in events if e.type == "example.interests"]
    assert len(append_events) == 1  # only the first (and only) one


async def test_emit_partial_includes_primitive_list_in_merge_delta(example_registry):
    emitter = EventEmitter(example_registry)
    me = ModelEmitter(emitter, "example", id="ex-1")

    p = ExampleModel.model_construct(tags=["ai", "cloud"], _fields_set={"tags"})
    await me.emit_partial(p)

    emitter.close()
    events = [e async for e in emitter.events()]
    merge_events = [e for e in events if e.type == "example"]
    assert len(merge_events) == 1
    data = merge_events[0].data.model_dump(exclude_unset=True)
    assert data == {"tags": ["ai", "cloud"]}


# ---------------------------------------------------------------------------
# ModelEmitter — done()
# ---------------------------------------------------------------------------


async def test_done_emits_merge_event_with_done_true(example_registry):
    emitter = EventEmitter(example_registry)
    me = ModelEmitter(emitter, "example", id="ex-1")

    await me.done()
    emitter.close()

    events = [e async for e in emitter.events()]
    assert len(events) == 1
    assert events[0].done is True
    assert events[0].type == "example"
    assert events[0].id == "ex-1"


async def test_done_is_idempotent(example_registry):
    emitter = EventEmitter(example_registry)
    me = ModelEmitter(emitter, "example", id="ex-1")

    await me.done()
    await me.done()  # second call is a no-op
    emitter.close()

    events = [e async for e in emitter.events()]
    assert len(events) == 1


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


async def test_context_manager_sends_done_on_exit(example_registry):
    emitter = EventEmitter(example_registry)

    async with ModelEmitter(emitter, "example", id="ex-1") as me:
        p = ExampleModel.model_construct(name="Nimbus", _fields_set={"name"})
        await me.emit_partial(p)

    emitter.close()
    events = [e async for e in emitter.events()]

    last = events[-1]
    assert last.done is True
    assert last.type == "example"


async def test_context_manager_does_not_close_underlying_emitter(example_registry):
    emitter = EventEmitter(example_registry)

    async with ModelEmitter(emitter, "example", id="ex-1") as me:
        pass  # done() is called; emitter should still be open

    # Emitter is still usable after ModelEmitter exits
    from ._models import LogLine

    log_registry = EventTypeRegistry()
    log_registry.register("log.line", LogLine, strategy="append")
    emitter2 = EventEmitter(log_registry)
    await emitter2.emit("log.line", LogLine(text="still open"), id="log-1")
    emitter2.close()
    events = [e async for e in emitter2.events()]
    assert len(events) == 1


# ---------------------------------------------------------------------------
# model_cls inference from first emit_partial call
# ---------------------------------------------------------------------------


async def test_model_cls_inferred_from_first_partial(example_registry):
    emitter = EventEmitter(example_registry)
    me = ModelEmitter(emitter, "example", id="ex-1")

    assert me._model_cls is None

    partial = ExampleModel.model_construct(name="Nimbus", _fields_set={"name"})
    await me.emit_partial(partial)

    assert me._model_cls is ExampleModel


# ---------------------------------------------------------------------------
# Default id falls back to prefix
# ---------------------------------------------------------------------------


async def test_default_id_uses_prefix_when_not_set(example_registry):
    emitter = EventEmitter(example_registry)
    me = ModelEmitter(emitter, "example")  # no id kwarg

    p = ExampleModel.model_construct(name="Nimbus", _fields_set={"name"})
    await me.emit_partial(p)
    emitter.close()

    events = [e async for e in emitter.events()]
    assert events[0].id == "example"


# ---------------------------------------------------------------------------
# Pydantic v1 compat
# ---------------------------------------------------------------------------
# NOTE: Pydantic v1 models must be defined at module level (not inside
# async functions) when ``from __future__ import annotations`` is active.
# With lazy annotations, pydantic v1 cannot resolve ForwardRefs for names
# that are only in the local function scope, so ``field.shape`` and
# ``field.type_`` are not evaluated correctly. This matches real usage —
# production models are always module-level.

from pydantic.v1 import BaseModel as _V1BaseModel

class _V1Interest(_V1BaseModel):
    name: str
    score: str


class _V1Example(_V1BaseModel):
    name: str | None = None
    title: str | None = None
    interests: list[_V1Interest] = []  # list[X] syntax works in Python 3.9+


async def test_register_model_and_emit_partial_with_pydantic_v1_model():
    registry = EventTypeRegistry()
    registry.register_model("v1example", _V1Example)

    assert "v1example" in registry
    assert "v1example.interests" in registry
    assert registry.get("v1example.interests").schema is _V1Interest

    emitter = EventEmitter(registry)
    me = ModelEmitter(emitter, "v1example", id="v1-1")

    partial = _V1Example.construct(
        name="Nimbus",
        interests=[_V1Interest(name="ML", score="high")],
        __fields_set__={"name", "interests"},
    )
    await me.emit_partial(partial)
    # done() flushes the pending last list item.
    await me.done()
    emitter.close()

    events = [e async for e in emitter.events()]
    merge_events = [e for e in events if e.type == "v1example"]
    append_events = [e for e in events if e.type == "v1example.interests"]

    # done() emits a second merge event (the done=True sentinel), so ≥ 1.
    assert len(merge_events) >= 1
    assert merge_events[0].data.name == "Nimbus"
    assert len(append_events) == 1
    assert append_events[0].data.name == "ML"
