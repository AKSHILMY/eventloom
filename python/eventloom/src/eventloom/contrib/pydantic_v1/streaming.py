"""Consume a stream of ever-more-complete partial objects and yield each
element of a growing list field exactly once, as soon as it's safe.

This is the `eventloom.contrib.pydantic_v1` analog of `instructor`'s
`create_iterable()` — but built as a standalone helper over `.stream()`
rather than a separate provider mode, since a single object with a list field
(streamed field-by-field like anything else) already carries the same
information; the only new piece needed is *when* it's safe to hand an
element to a caller instead of re-showing it every chunk.

Generalizes the exact hand-rolled watermark pattern already proven in
production (`coachello-back/services/core/roleplay_service.py`,
`_stream_section_with_criteria`):

    last_emitted = 0
    async for partial in stream_client.stream(...):
        criterias = getattr(partial.evaluation_grid[0], 'criterias', None) or []
        while last_emitted < len(criterias) - 1:
            c = criterias[last_emitted]
            if c and getattr(c, 'title', None) and getattr(c, 'applicable', None) is True:
                emit(c)
            last_emitted += 1
    # + a final flush of whatever's left once the stream ends.

`stream_new_list_items()` below is that pattern, reusable for any list field.
"""

from typing import AsyncIterator, Callable, List, Optional, TypeVar

M = TypeVar("M")
Item = TypeVar("Item")


async def stream_new_list_items(
    partials: AsyncIterator[M],
    get_list: Callable[[M], Optional[List[Item]]],
    *,
    is_complete: Callable[[Item], bool] = lambda item: True,
) -> AsyncIterator[Item]:
    """Yield each element of a growing list field exactly once.

    An item at index `i` is only ever considered safe to yield once the list
    has grown past it (index `i + 1` exists) — nothing can append further
    data onto item `i` once a later item has started. Once the underlying
    stream ends, whatever's left (including the very last item, which never
    gets a "the list grew past it" signal mid-stream) is flushed.

    Args:
        partials: An async iterator of ever-more-complete partial objects,
            e.g. `ProviderStreamClient.stream(...)`.
        get_list: Extracts the growing list field from a partial object.
            Returning `None` (e.g. the field hasn't streamed in yet) is
            treated the same as an empty list.
        is_complete: Optional extra gate before yielding an item — e.g.
            check that its own required-looking fields are non-empty. If it
            returns `False`, that index is *retried* on the next partial
            (not permanently skipped) — this is a deliberate correctness
            improvement over the original hand-rolled pattern above, which
            always advanced its watermark regardless of the check's outcome
            and could silently drop an item whose fields hadn't caught up
            yet if the model streamed slightly out of left-to-right order.
            The trade-off: yielding pauses on a stuck index until it
            resolves or the stream ends (at which point it's flushed
            regardless of `is_complete`, since nothing more is coming).

    Yields:
        Each list element, in order, exactly once.
    """
    emitted = 0
    last_seen: List[Item] = []
    async for partial in partials:
        items = get_list(partial) or []
        last_seen = items
        while emitted < len(items) - 1:
            candidate = items[emitted]
            if not is_complete(candidate):
                break  # not ready yet — recheck the same index next partial
            yield candidate
            emitted += 1

    # Stream is over — nothing more is coming; flush whatever's left,
    # including the final item (which never gets a "grew past it" signal).
    while emitted < len(last_seen):
        candidate = last_seen[emitted]
        if is_complete(candidate):
            yield candidate
        emitted += 1
