"""FastAPI-specific: drains an `EventEmitter` into a `StreamingResponse`.

This is genuinely ~20 lines of adapter code by design (plan section 3.3) —
the value is in `core`'s registry/emitter/envelope model being solid, not in
the FastAPI glue.
"""

from __future__ import annotations

from typing import Awaitable, Callable, AsyncIterator

import anyio
from fastapi import Request
from fastapi.responses import StreamingResponse

from ...core.emitter import EventEmitter
from ...core.envelope import StreamEnvelope
from ...core.serializers import Serializer, default_serializer

#: Headers that keep proxies (nginx, and friends) from buffering the response,
#: which would defeat the purpose of streaming. Applied by default; pass your
#: own `headers=` to `to_sse_response` to override/extend.
_DEFAULT_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

Producer = Callable[[], Awaitable[None]]


def to_sse_response(
    emitter: EventEmitter,
    *,
    run: Producer | None = None,
    serializer: Serializer = default_serializer,
    request: Request | None = None,
    headers: dict[str, str] | None = None,
) -> StreamingResponse:
    """Wrap an `EventEmitter` in a FastAPI `StreamingResponse` over SSE.

    Each envelope produced by `emitter.events()` becomes one `data:` line. If
    `request` is given, the generator stops early when the client disconnects
    (`request.is_disconnected()`) instead of emitting into the void.

    **Error handling.** Emitting logic almost always runs concurrently with
    draining (e.g. a background task started with `asyncio.create_task`), so
    an exception it raises does *not* automatically propagate into this
    function's drain loop — it happens in a different task. Two ways to get
    it converted into a `__stream_error__` envelope (see `StreamError`) and
    sent to the client before the connection closes:

    1. **Preferred — pass `run`.** Give `to_sse_response` the producer
       coroutine function directly and it manages the task, catches
       exceptions, and closes the emitter for you:

           @app.get("/stream/dashboard")
           async def dashboard_stream(emitter: EventEmitter = Depends(get_emitter)):
               async def run():
                   await emitter.emit("chart.data", ChartData(...), id="chart-1", done=True)
               return to_sse_response(emitter, run=run)

    2. **Manual task management.** If you start your own task (e.g. because
       it needs to outlive this function, or you're not using FastAPI's
       request-scoped dependency), catch errors yourself and call
       `emitter.emit_error()` / `emitter.close()` in a `finally` block —
       `to_sse_response`'s own try/except only covers exceptions raised while
       iterating/serializing within its *own* drain loop, not a separate task.
    """

    async def drive_producer() -> None:
        assert run is not None
        try:
            await run()
        except Exception as exc:  # noqa: BLE001 - last line of defense for the producer
            await emitter.emit_error(str(exc), code=type(exc).__name__)
        finally:
            emitter.close()

    async def gen() -> AsyncIterator[str]:
        async with anyio.create_task_group() as tg:
            if run is not None:
                tg.start_soon(drive_producer)
            try:
                async for envelope in emitter.events():
                    if request is not None and await request.is_disconnected():
                        break
                    yield _format_sse(envelope, serializer)
            except Exception as exc:  # noqa: BLE001 - deliberately broad: last line of defense
                error_envelope = await emitter.emit_error(str(exc), code=type(exc).__name__)
                yield _format_sse(error_envelope, serializer)
            finally:
                emitter.close()

    merged_headers = {**_DEFAULT_SSE_HEADERS, **(headers or {})}
    return StreamingResponse(gen(), media_type="text/event-stream", headers=merged_headers)


def _format_sse(envelope: StreamEnvelope, serializer: Serializer) -> str:
    # `event:` mirrors `type` for SSE clients/tooling that filter on it (e.g.
    # browser devtools), but per the wire protocol (plan section 2) the JSON
    # `data:` body is the single source of truth — no client should need to
    # read the SSE `event:` field to parse a payload.
    return f"event: {envelope.type}\ndata: {serializer.dumps(envelope)}\n\n"
