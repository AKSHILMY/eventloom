"""Tests for eventloom.contrib.pydantic_v1.streaming.stream_new_list_items."""

from typing import List, Optional

from eventloom.contrib.pydantic_v1 import BaseModel
from eventloom.contrib.pydantic_v1.streaming import stream_new_list_items


class Item(BaseModel):
    title: Optional[str] = None
    ready: Optional[bool] = None


class Batch(BaseModel):
    items: List[Item] = []


async def _partials(*snapshots: List[Item]):
    for snapshot in snapshots:
        yield Batch(items=snapshot)


async def test_yields_items_only_once_list_has_grown_past_them():
    snapshots = [
        [Item(title="a")],
        [Item(title="a"), Item(title="b")],
        [Item(title="a"), Item(title="b"), Item(title="c")],
    ]
    yielded = [item async for item in stream_new_list_items(_partials(*snapshots), get_list=lambda b: b.items)]
    # "a" becomes safe once "b" exists, "b" once "c" exists; "c" only flushed
    # at stream end (it never gets a "grew past it" signal mid-stream).
    assert [i.title for i in yielded] == ["a", "b", "c"]


async def test_flushes_remaining_items_at_stream_end_even_with_one_snapshot():
    snapshots = [[Item(title="only")]]
    yielded = [item async for item in stream_new_list_items(_partials(*snapshots), get_list=lambda b: b.items)]
    assert [i.title for i in yielded] == ["only"]


async def test_empty_list_field_yields_nothing():
    snapshots = [[], []]
    yielded = [item async for item in stream_new_list_items(_partials(*snapshots), get_list=lambda b: b.items)]
    assert yielded == []


async def test_get_list_returning_none_is_treated_as_empty():
    async def partials():
        yield Batch(items=[])

    yielded = [item async for item in stream_new_list_items(partials(), get_list=lambda b: None)]
    assert yielded == []


async def test_is_complete_false_retries_same_index_instead_of_skipping():
    snapshots = [
        [Item(title="a", ready=False), Item(title="b", ready=True)],
        [Item(title="a", ready=True), Item(title="b", ready=True), Item(title="c", ready=True)],
    ]
    yielded = [
        item
        async for item in stream_new_list_items(
            _partials(*snapshots), get_list=lambda b: b.items, is_complete=lambda i: bool(i.ready)
        )
    ]
    # "a" wasn't ready on the first snapshot (index 0, list length 2 — safe to
    # check but not complete), so it's retried, not dropped, once it becomes
    # ready on the second snapshot.
    assert [i.title for i in yielded] == ["a", "b", "c"]


async def test_is_complete_false_at_stream_end_still_gets_flushed_only_if_complete():
    snapshots = [[Item(title="a", ready=False)]]
    yielded = [
        item
        async for item in stream_new_list_items(
            _partials(*snapshots), get_list=lambda b: b.items, is_complete=lambda i: bool(i.ready)
        )
    ]
    assert yielded == []  # never became ready — not flushed
