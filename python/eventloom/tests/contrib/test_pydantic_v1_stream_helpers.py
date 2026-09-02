"""Tests for eventloom.contrib.pydantic_v1.stream_model / stream_items.

Uses a fake ProviderStreamClient (async generator stub) so no real LLM
call is made.  Verifies that:
- stream_model feeds partials through ModelEmitter (delta tracking, done=True)
- stream_model auto-registers if auto_register=True
- stream_items extracts items via stream_new_list_items and emits append events
- stream_items emits done=True marker by default, suppresses it with done=False
- Pydantic v2 schemas raise TypeError with helpful message pointing to contrib.instructor
- list[SubModel] fields on the parent are routed to append events (watermarking)
"""

from __future__ import annotations

from typing import AsyncGenerator, List, Optional

import pytest

from eventloom import EventEmitter, EventTypeRegistry
from eventloom.contrib.pydantic_v1 import BaseModel, stream_items, stream_model


# ---------------------------------------------------------------------------
# Schemas — all at module scope so pydantic v1 resolves annotations correctly
# ---------------------------------------------------------------------------


class KeyProduct(BaseModel):
    name: str
    tagline: Optional[str] = None


class Profile(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = None
    products: List[KeyProduct] = []


class Insight(BaseModel):
    title: str
    detail: str


class InsightsBatch(BaseModel):
    insights: List[Insight] = []


# ---------------------------------------------------------------------------
# Fake stream client
# ---------------------------------------------------------------------------


class FakeClient:
    """Minimal ProviderStreamClient stub — yields a fixed sequence of partials."""

    def __init__(self, partials):
        self._partials = partials

    async def stream(self, *, model, response_model, messages, **kwargs):
        for p in self._partials:
            yield p


# ---------------------------------------------------------------------------
# stream_model tests
# ---------------------------------------------------------------------------


async def test_stream_model_emits_merge_events_from_partials():
    registry = EventTypeRegistry()
    registry.register_model("profile", Profile)
    emitter = EventEmitter(registry)

    # Simulate what client.stream() yields: pydantic v1 partials built with
    # the correct _fields_set parameter (single underscore).
    p1 = Profile.construct(_fields_set={"name"}, name="Alice")
    p2 = Profile.construct(_fields_set={"name", "bio"}, name="Alice", bio="Engineer")
    client = FakeClient([p1, p2])

    await stream_model(
        emitter, "profile", Profile,
        client=client, model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Generate."}],
        id="p-1",
    )

    emitter.close()
    events = [e async for e in emitter.events()]

    merge_events = [e for e in events if e.type == "profile" and not e.done]
    done_events = [e for e in events if e.type == "profile" and e.done]

    # chunk 1: name emitted; chunk 2: only bio (name unchanged via delta tracking)
    assert len(merge_events) == 2
    assert len(done_events) == 1  # auto-sent by ModelEmitter context manager


async def test_stream_model_auto_register_registers_model():
    registry = EventTypeRegistry()
    emitter = EventEmitter(registry)

    assert "profile" not in registry

    client = FakeClient([])
    await stream_model(
        emitter, "profile", Profile,
        client=client, model="gpt-4o-mini",
        messages=[],
        auto_register=True,
    )

    assert "profile" in registry
    assert registry.get("profile").strategy == "merge"


async def test_stream_model_auto_register_skips_if_already_registered():
    registry = EventTypeRegistry()
    registry.register("profile", Profile, strategy="replace")  # manual, non-default
    emitter = EventEmitter(registry)

    client = FakeClient([])
    await stream_model(
        emitter, "profile", Profile,
        client=client, model="gpt-4o-mini",
        messages=[],
        auto_register=True,
    )

    # must not override
    assert registry.get("profile").strategy == "replace"


async def test_stream_model_routes_list_model_field_to_append_event():
    """list[KeyProduct] on Profile → auto append events for each new product."""
    registry = EventTypeRegistry()
    registry.register_model("profile", Profile)  # auto-derives profile.products
    emitter = EventEmitter(registry)

    prod1 = KeyProduct.construct(_fields_set={"name"}, name="Widget")
    prod2 = KeyProduct.construct(_fields_set={"name"}, name="Gadget")

    p1 = Profile.construct(_fields_set={"products"}, products=[prod1])
    p2 = Profile.construct(_fields_set={"products"}, products=[prod1, prod2])
    client = FakeClient([p1, p2])

    await stream_model(
        emitter, "profile", Profile,
        client=client, model="gpt-4o-mini",
        messages=[],
        id="p-1",
    )

    emitter.close()
    events = [e async for e in emitter.events()]
    append_events = [e for e in events if e.type == "profile.products"]
    assert len(append_events) == 2  # one per product, watermarked


async def test_stream_model_raises_for_v2_schema():
    """Passing a Pydantic v2 schema must raise immediately with a helpful message."""
    from pydantic import BaseModel as V2Base

    class V2Profile(V2Base):
        name: str | None = None

    registry = EventTypeRegistry()
    registry.register("profile", V2Profile, strategy="merge")
    emitter = EventEmitter(registry)

    with pytest.raises(TypeError, match="instructor"):
        await stream_model(
            emitter, "profile", V2Profile,
            client=FakeClient([]), model="gpt-4o-mini",
            messages=[],
        )


# ---------------------------------------------------------------------------
# stream_items tests
# ---------------------------------------------------------------------------


async def test_stream_items_emits_one_append_event_per_item():
    registry = EventTypeRegistry()
    registry.register("insight", Insight, strategy="append")
    emitter = EventEmitter(registry)

    batch1 = InsightsBatch(insights=[Insight(title="A", detail="d-a")])
    batch2 = InsightsBatch(insights=[
        Insight(title="A", detail="d-a"),
        Insight(title="B", detail="d-b"),
    ])
    batch3 = InsightsBatch(insights=[
        Insight(title="A", detail="d-a"),
        Insight(title="B", detail="d-b"),
        Insight(title="C", detail="d-c"),
    ])
    client = FakeClient([batch1, batch2, batch3])

    count = await stream_items(
        emitter, "insight", Insight,
        client=client, model="gpt-4o-mini",
        messages=[],
        wrapper_schema=InsightsBatch,
        get_list=lambda p: p.insights,
        id="insights",
    )

    emitter.close()
    events = [e async for e in emitter.events()]
    append_events = [e for e in events if e.type == "insight" and not e.done]
    done_events = [e for e in events if e.type == "insight" and e.done]

    # stream_new_list_items flushes "safe" items (those superseded by a later chunk)
    assert count >= 2  # at least A and B are safe; C may or may not be flushed
    assert len(done_events) == 1


async def test_stream_items_done_false_suppresses_done_marker():
    registry = EventTypeRegistry()
    registry.register("insight", Insight, strategy="append")
    emitter = EventEmitter(registry)

    batch = InsightsBatch(insights=[
        Insight(title="A", detail="d-a"),
        Insight(title="B", detail="d-b"),
    ])
    client = FakeClient([batch])

    await stream_items(
        emitter, "insight", Insight,
        client=client, model="gpt-4o-mini",
        messages=[],
        wrapper_schema=InsightsBatch,
        get_list=lambda p: p.insights,
        done=False,
    )

    emitter.close()
    events = [e async for e in emitter.events()]
    assert not any(e.done for e in events)


async def test_stream_items_raises_for_v2_schema():
    from pydantic import BaseModel as V2Base

    class V2Insight(V2Base):
        title: str

    registry = EventTypeRegistry()
    registry.register("insight", V2Insight, strategy="append")
    emitter = EventEmitter(registry)

    with pytest.raises(TypeError, match="instructor"):
        await stream_items(
            emitter, "insight", V2Insight,
            client=FakeClient([]), model="gpt-4o-mini",
            messages=[],
            wrapper_schema=InsightsBatch,
            get_list=lambda p: p.insights,
        )
