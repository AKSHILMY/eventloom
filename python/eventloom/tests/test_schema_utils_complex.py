"""Tests for complex schema support in schema_utils and ModelEmitter.

Covers edge cases not in the basic test_model_emitter.py:
- set[Model] and frozenset[Model] fields
- Optional[list[Model]] fields
- Pydantic v2 complex annotations
"""

from __future__ import annotations

from pydantic import BaseModel

from eventloom import EventEmitter, EventTypeRegistry, ModelEmitter


# ---------------------------------------------------------------------------
# Schemas for complex type testing
# ---------------------------------------------------------------------------


class TagModel(BaseModel):
    label: str
    weight: float = 1.0

    # Make hashable so instances can go into set / frozenset fields.
    def __hash__(self) -> int:  # type: ignore[override]
        return hash((self.label, self.weight))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TagModel):
            return NotImplemented
        return self.label == other.label and self.weight == other.weight


class ComplexModel(BaseModel):
    name: str | None = None
    tags_list: list[TagModel] = []
    tags_set: set[TagModel] = set()
    tags_frozen: frozenset[TagModel] = frozenset()
    tags_primitive: list[str] = []       # primitive list → stays in merge
    score: float | None = None


class OptionalListModel(BaseModel):
    """Model with Optional[list[Model]] field."""
    name: str | None = None
    items: list[TagModel] | None = None   # Optional[list[Model]]


# ---------------------------------------------------------------------------
# register_model with set / frozenset fields
# ---------------------------------------------------------------------------


def test_register_model_detects_set_field():
    registry = EventTypeRegistry()
    registry.register_model("complex", ComplexModel)
    # set[TagModel] should get a separate append event
    assert "complex.tags_set" in registry
    assert registry.get("complex.tags_set").strategy == "append"
    assert registry.get("complex.tags_set").schema is TagModel


def test_register_model_detects_frozenset_field():
    registry = EventTypeRegistry()
    registry.register_model("complex", ComplexModel)
    assert "complex.tags_frozen" in registry
    assert registry.get("complex.tags_frozen").schema is TagModel


def test_register_model_detects_list_field():
    registry = EventTypeRegistry()
    registry.register_model("complex", ComplexModel)
    assert "complex.tags_list" in registry


def test_register_model_skips_primitive_list():
    registry = EventTypeRegistry()
    registry.register_model("complex", ComplexModel)
    # list[str] should NOT get a separate event
    assert "complex.tags_primitive" not in registry


def test_register_model_detects_optional_list_field():
    """Optional[list[Model]] should still get its own append event."""
    registry = EventTypeRegistry()
    registry.register_model("optlist", OptionalListModel)
    assert "optlist.items" in registry
    assert registry.get("optlist.items").schema is TagModel


# ---------------------------------------------------------------------------
# emit_partial with set fields
# ---------------------------------------------------------------------------


async def _make_registry_and_emitter():
    registry = EventTypeRegistry()
    registry.register_model("complex", ComplexModel)
    return registry, EventEmitter(registry)


async def test_emit_partial_handles_set_of_models():
    registry, emitter = await _make_registry_and_emitter()
    me = ModelEmitter(emitter, "complex", id="c-1")

    tag1 = TagModel(label="ai", weight=1.0)
    tag2 = TagModel(label="ml", weight=0.8)

    # Chunk 1: one item in the set
    p1 = ComplexModel.model_construct(
        tags_set={tag1},
        _fields_set={"tags_set"},
    )
    await me.emit_partial(p1)

    # Chunk 2: two items
    p2 = ComplexModel.model_construct(
        tags_set={tag1, tag2},
        _fields_set={"tags_set"},
    )
    await me.emit_partial(p2)
    await me.done()

    emitter.close()
    events = [e async for e in emitter.events()]
    append_events = [e for e in events if e.type == "complex.tags_set"]
    assert len(append_events) == 2


async def test_emit_partial_handles_frozenset_of_models():
    registry, emitter = await _make_registry_and_emitter()
    me = ModelEmitter(emitter, "complex", id="c-1")

    tag = TagModel(label="nlp", weight=0.9)
    p = ComplexModel.model_construct(
        tags_frozen=frozenset([tag]),
        _fields_set={"tags_frozen"},
    )
    await me.emit_partial(p)
    await me.done()
    emitter.close()

    events = [e async for e in emitter.events()]
    append_events = [e for e in events if e.type == "complex.tags_frozen"]
    assert len(append_events) == 1
    assert append_events[0].data.label == "nlp"


async def test_emit_partial_handles_optional_list_field():
    registry = EventTypeRegistry()
    registry.register_model("optlist", OptionalListModel)
    emitter = EventEmitter(registry)
    me = ModelEmitter(emitter, "optlist", id="ol-1")

    tag = TagModel(label="ai")
    p = OptionalListModel.model_construct(
        items=[tag],
        _fields_set={"items"},
    )
    await me.emit_partial(p)
    await me.done()
    emitter.close()

    events = [e async for e in emitter.events()]
    append_events = [e for e in events if e.type == "optlist.items"]
    assert len(append_events) == 1
    assert append_events[0].data.label == "ai"
