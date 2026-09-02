"""Tests for eventloom.contrib.instructor.stream_model / stream_items.

Uses unittest.mock to stub out ``instructor.from_provider`` so no real LLM
call is made. Verifies that:
- stream_model calls create_partial and feeds partials to ModelEmitter
- stream_items calls create_iterable and emits each item as an append event
- auto_register registers the model if not yet in the registry
- ImportError is raised cleanly if instructor is not installed
- provider_model string is forwarded to instructor.from_provider unchanged
- Pydantic v1 schemas raise TypeError with helpful message
"""

from __future__ import annotations

from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from eventloom import EventEmitter, EventTypeRegistry
from eventloom.contrib.instructor import stream_items, stream_model
from eventloom.contrib.pydantic_v1 import BaseModel as V1BaseModel


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class Profile(BaseModel):
    name: str | None = None
    bio: str | None = None


class InsightItem(BaseModel):
    title: str


# Pydantic v1 schema — used to verify that the v1 guard fires before any
# instructor call is made.  Must be at module scope (not inside a function) so
# pydantic.v1 resolves field annotations correctly.
class V1Profile(V1BaseModel):
    name: str | None = None
    bio: str | None = None
    detail: str


# ---------------------------------------------------------------------------
# Helpers: fake async generators
# ---------------------------------------------------------------------------


async def _partial_gen(*partials):
    """Yield each item in *partials* as if from create_partial."""
    for p in partials:
        yield p


async def _iterable_gen(*items):
    """Yield each item in *items* as if from create_iterable."""
    for item in items:
        yield item


# ---------------------------------------------------------------------------
# stream_model tests
# ---------------------------------------------------------------------------


def _make_instructor_mock(partials, mode="partial"):
    """Return a mock instructor client whose create_partial / create_iterable
    returns the given sequence of items."""
    mock_client = MagicMock()
    if mode == "partial":
        mock_client.create_partial = MagicMock(return_value=_partial_gen(*partials))
    else:
        mock_client.create_iterable = MagicMock(return_value=_iterable_gen(*partials))
    return mock_client


async def test_stream_model_emits_merge_events_from_partials():
    registry = EventTypeRegistry()
    registry.register_model("profile", Profile)
    emitter = EventEmitter(registry)

    partials = [
        Profile.model_construct(name="Alice", _fields_set={"name"}),
        Profile.model_construct(name="Alice", bio="Engineer", _fields_set={"name", "bio"}),
    ]
    mock_client = _make_instructor_mock(partials, mode="partial")

    with patch("eventloom.contrib.instructor.stream._get_async_client", return_value=mock_client):
        await stream_model(
            emitter, "profile", Profile,
            provider_model="openai/gpt-4o-mini",
            messages=[{"role": "user", "content": "Generate a profile."}],
            id="p-1",
        )

    emitter.close()
    events = [e async for e in emitter.events()]

    merge_events = [e for e in events if e.type == "profile" and not e.done]
    done_events = [e for e in events if e.type == "profile" and e.done]

    # Partial 1: name emitted, partial 2: only bio (name unchanged)
    assert len(merge_events) == 2
    assert merge_events[0].data.model_dump(exclude_unset=True) == {"name": "Alice"}
    assert merge_events[1].data.model_dump(exclude_unset=True) == {"bio": "Engineer"}

    # done=True sent on context-manager exit
    assert len(done_events) == 1


async def test_stream_model_forwards_provider_model_to_instructor():
    registry = EventTypeRegistry()
    registry.register_model("profile", Profile)
    emitter = EventEmitter(registry)

    captured_args: list = []

    def fake_get_async_client(provider_model: str, **kwargs):
        captured_args.append(provider_model)
        mock = MagicMock()
        mock.create_partial = MagicMock(return_value=_partial_gen())
        return mock

    with patch("eventloom.contrib.instructor.stream._get_async_client", side_effect=fake_get_async_client):
        await stream_model(
            emitter, "profile", Profile,
            provider_model="anthropic/claude-haiku-4-5-latest",
            messages=[],
            id="p-1",
        )

    assert captured_args == ["anthropic/claude-haiku-4-5-latest"]


async def test_stream_model_auto_register_adds_model_if_missing():
    registry = EventTypeRegistry()
    emitter = EventEmitter(registry)

    assert "profile" not in registry

    mock_client = _make_instructor_mock([], mode="partial")
    with patch("eventloom.contrib.instructor.stream._get_async_client", return_value=mock_client):
        await stream_model(
            emitter, "profile", Profile,
            provider_model="openai/gpt-4o-mini",
            messages=[],
            auto_register=True,
        )

    assert "profile" in registry
    assert registry.get("profile").strategy == "merge"


async def test_stream_model_auto_register_skips_if_already_registered():
    registry = EventTypeRegistry()
    registry.register("profile", Profile, strategy="replace")  # manually registered
    emitter = EventEmitter(registry)

    mock_client = _make_instructor_mock([], mode="partial")
    with patch("eventloom.contrib.instructor.stream._get_async_client", return_value=mock_client):
        await stream_model(
            emitter, "profile", Profile,
            provider_model="openai/gpt-4o-mini",
            messages=[],
            auto_register=True,
        )

    # Should not override the manual registration
    assert registry.get("profile").strategy == "replace"


async def test_stream_model_raises_import_error_when_instructor_missing():
    registry = EventTypeRegistry()
    registry.register_model("profile", Profile)
    emitter = EventEmitter(registry)

    with patch.dict("sys.modules", {"instructor": None}):
        with pytest.raises(ImportError, match="instructor"):
            await stream_model(
                emitter, "profile", Profile,
                provider_model="openai/gpt-4o-mini",
                messages=[],
            )


# ---------------------------------------------------------------------------
# stream_items tests
# ---------------------------------------------------------------------------


async def test_stream_items_emits_one_append_event_per_item():
    registry = EventTypeRegistry()
    registry.register("insight", InsightItem, strategy="append")
    emitter = EventEmitter(registry)

    items = [
        InsightItem(title="A", detail="detail-a"),
        InsightItem(title="B", detail="detail-b"),
        InsightItem(title="C", detail="detail-c"),
    ]
    mock_client = _make_instructor_mock(items, mode="iterable")

    with patch("eventloom.contrib.instructor.stream._get_async_client", return_value=mock_client):
        count = await stream_items(
            emitter, "insight", InsightItem,
            provider_model="openai/gpt-4o-mini",
            messages=[{"role": "user", "content": "Generate insights."}],
            id="insights",
        )

    emitter.close()
    events = [e async for e in emitter.events()]

    append_events = [e for e in events if e.type == "insight" and not e.done]
    done_events = [e for e in events if e.type == "insight" and e.done]

    assert count == 3
    assert len(append_events) == 3
    assert [e.data.title for e in append_events] == ["A", "B", "C"]
    assert all(e.id == "insights" for e in append_events)
    # done marker emitted
    assert len(done_events) == 1


async def test_stream_items_no_done_marker_on_empty_stream():
    registry = EventTypeRegistry()
    registry.register("insight", InsightItem, strategy="append")
    emitter = EventEmitter(registry)

    mock_client = _make_instructor_mock([], mode="iterable")
    with patch("eventloom.contrib.instructor.stream._get_async_client", return_value=mock_client):
        count = await stream_items(
            emitter, "insight", InsightItem,
            provider_model="openai/gpt-4o-mini",
            messages=[],
        )

    emitter.close()
    events = [e async for e in emitter.events()]
    assert count == 0
    assert len(events) == 0  # no done marker if nothing was emitted


async def test_stream_items_done_false_suppresses_done_marker():
    registry = EventTypeRegistry()
    registry.register("insight", InsightItem, strategy="append")
    emitter = EventEmitter(registry)

    items = [InsightItem(title="X", detail="d")]
    mock_client = _make_instructor_mock(items, mode="iterable")
    with patch("eventloom.contrib.instructor.stream._get_async_client", return_value=mock_client):
        await stream_items(
            emitter, "insight", InsightItem,
            provider_model="openai/gpt-4o-mini",
            messages=[],
            done=False,
        )

    emitter.close()
    events = [e async for e in emitter.events()]
    assert not any(e.done for e in events)


async def test_stream_items_default_id_is_event_type():
    registry = EventTypeRegistry()
    registry.register("insight", InsightItem, strategy="append")
    emitter = EventEmitter(registry)

    items = [InsightItem(title="X", detail="d")]
    mock_client = _make_instructor_mock(items, mode="iterable")
    with patch("eventloom.contrib.instructor.stream._get_async_client", return_value=mock_client):
        await stream_items(
            emitter, "insight", InsightItem,
            provider_model="openai/gpt-4o-mini",
            messages=[],
            done=False,
        )

    emitter.close()
    events = [e async for e in emitter.events()]
    assert events[0].id == "insight"


# ---------------------------------------------------------------------------
# Pydantic v1 guard — must raise before instructor is ever called
# ---------------------------------------------------------------------------


async def test_stream_model_raises_type_error_for_v1_schema():
    """stream_model must reject Pydantic v1 schemas immediately."""
    registry = EventTypeRegistry()
    registry.register_model("profile", Profile)  # v2 registration is fine
    emitter = EventEmitter(registry)

    with pytest.raises(TypeError, match="pydantic_v1"):
        # _get_async_client must never be reached — no patch needed.
        await stream_model(
            emitter, "profile", V1Profile,
            provider_model="openai/gpt-4o-mini",
            messages=[],
        )


async def test_stream_items_raises_type_error_for_v1_schema():
    """stream_items must reject Pydantic v1 schemas immediately."""
    registry = EventTypeRegistry()
    registry.register("insight", InsightItem, strategy="append")
    emitter = EventEmitter(registry)

    with pytest.raises(TypeError, match="pydantic_v1"):
        await stream_items(
            emitter, "insight", V1Profile,
            provider_model="openai/gpt-4o-mini",
            messages=[],
        )
