# eventloom

A generalized, deterministic backend-to-frontend event streaming toolkit for Python.

Define typed event types once, emit them from any async backend logic, and stream them
to the client over SSE — no LLM/agent required, no framework lock-in. Pairs with the
TypeScript [`@akshilmy/eventloom-core`](https://www.npmjs.com/package/@akshilmy/eventloom-core)
+ [`@akshilmy/eventloom-react`](https://www.npmjs.com/package/@akshilmy/eventloom-react)
packages on the frontend, but the wire protocol is framework- and language-agnostic —
any client that can parse JSON over SSE can consume it.

- **Core is framework-agnostic.** `eventloom.core` has zero dependency on FastAPI, Flask,
  or anything web-related — it's pure Pydantic + `anyio`.
- **FastAPI adapter is first-class** and ships in this package (`eventloom.adapters.fastapi`),
  gated behind an optional extra so installing plain `eventloom` never pulls in FastAPI.
- **Type-safe emission.** Every event type is declared with a Pydantic schema up front;
  emitting data that doesn't match raises `pydantic.ValidationError` at emit-time, not a
  silent bad payload on the wire.
- **Merge strategy is per event type.** `replace` (discrete events), `merge` (partial
  objects filling in over time), `append` (streaming lists/log lines/tokens) — declared
  once on the backend, and the frontend obeys it automatically.

## Install

```bash
pip install eventloom                 # core only
pip install "eventloom[fastapi]"      # + the FastAPI adapter
pip install "eventloom[pydantic-v1]"  # + partial-streaming from Pydantic v1 schemas
```

Requires Python 3.10+ and Pydantic v2 (event *payloads* can still be Pydantic v1 — see
[Pydantic v1 compatibility](#pydantic-v1-compatibility-eventloomcontribpydantic_v1) below).

## Quickstart

**1. Declare your event types** (typically in a shared module, e.g. `myapp/events.py`):

```python
from pydantic import BaseModel
from eventloom import EventTypeRegistry

registry = EventTypeRegistry()

class ChartData(BaseModel):
    labels: list[str]
    values: list[float]

registry.register("chart.data", ChartData, strategy="replace")

class UserProfile(BaseModel):
    name: str | None = None
    bio: str | None = None

registry.register("user.partial", UserProfile, strategy="merge")

class LogLine(BaseModel):
    text: str

registry.register("log.line", LogLine, strategy="append")
```

**2. Emit events from an endpoint** using the FastAPI adapter:

```python
from fastapi import FastAPI, Depends
from eventloom import EventEmitter
from eventloom.adapters.fastapi import emitter_dependency, to_sse_response
from myapp.events import registry, ChartData

app = FastAPI()
get_emitter = emitter_dependency(registry)

@app.get("/stream/dashboard")
async def dashboard_stream(emitter: EventEmitter = Depends(get_emitter)):
    async def run():
        await emitter.emit(
            "chart.data",
            ChartData(labels=["Q1", "Q2"], values=[120.0, 150.0]),
            id="chart-1",
            done=True,
        )
        # ... more emits, from any async logic — DB polling, pubsub, whatever

    return to_sse_response(emitter, run=run)
```

`to_sse_response(emitter, run=run)` runs `run()` alongside draining, closes the emitter
when it finishes, and — if `run()` raises — converts the exception into a
`__stream_error__` envelope automatically (see [Error handling](#error-handling-contract)
below). You can still manage your own background task instead (e.g.
`asyncio.create_task(...)`) if it needs to outlive this function, but then you're
responsible for calling `emitter.emit_error()` / `emitter.close()` yourself.

**3. Point a frontend at it** — see
[`@akshilmy/eventloom-react`](https://www.npmjs.com/package/@akshilmy/eventloom-react)'s
README for the matching `<StreamView endpoint="/stream/dashboard" registry={registry} />`.

That endpoint now emits a standards-compliant SSE stream where every `data:` line is a
JSON [`StreamEnvelope`](#wire-protocol) — inspect it yourself:

```bash
curl -N http://localhost:8000/stream/dashboard
```

```
event: chart.data
data: {"type":"chart.data","id":"chart-1","seq":0,"data":{"labels":["Q1","Q2"],"values":[120.0,150.0]},"strategy":"replace","done":true,"ts":"2026-08-18T12:00:00+00:00"}
```

## Wire protocol

Every event on the wire is one JSON object per SSE `data:` line:

```ts
interface StreamEnvelope<T = unknown> {
  type: string;      // event type, e.g. "chart.data" — routes to a component on the frontend
  id: string;         // groups events belonging to the same logical "thing"
  seq: number;         // monotonic sequence number within this `id`
  data: T;              // event-specific payload
  strategy: "replace" | "merge" | "append";
  done: boolean;          // true if this is the final event for this `id`
  ts: string;               // ISO timestamp
}
```

This is the contract the Python and TypeScript packages both implement — it's frozen and
versioned independently of either package, so you could write a Go backend or a Svelte
frontend against it without touching either package. See the [project plan / wire
protocol reference](../../../eventloom-project-plan.md#2-wire-protocol-the-contract-both-packages-implement)
for the full rationale.

## Core API

### `EventTypeRegistry`

```python
from eventloom import EventTypeRegistry

registry = EventTypeRegistry()
registry.register(type_name: str, schema: type[BaseModel], strategy: "replace" | "merge" | "append" = "replace")
registry.get(type_name: str) -> EventTypeSpec       # raises UnknownEventTypeError if unregistered
type_name in registry                                  # membership check
```

Registering the same `type_name` twice with an identical schema/strategy is a no-op
(safe for shared modules imported from multiple entry points). Registering it twice with
a *different* schema or strategy raises `DuplicateEventTypeError`.

### `EventEmitter`

```python
from eventloom import EventEmitter

emitter = EventEmitter(registry, group_id=None)

await emitter.emit(type_name: str, data: BaseModel | dict, id: str | None = None, done: bool = False) -> StreamEnvelope
await emitter.emit_error(message: str, code: str | None = None) -> StreamEnvelope  # emits "__stream_error__"
emitter.close()      # signal no more events; events() stops once drained
async for envelope in emitter.events(): ...           # what an adapter drains
```

`data` may be an instance of the registered schema, or a plain `dict` (validated via
`schema.model_validate`). `id` defaults to `type_name` if omitted — pass an explicit `id`
whenever multiple events share the same logical grouping (e.g. every partial update to one
chart uses `id="chart-1"`).

`EventEmitter` also works as an async context manager, closing itself on exit:

```python
async with EventEmitter(registry) as emitter:
    await emitter.emit("chart.data", ChartData(...), id="chart-1", done=True)
```

### `StreamEnvelope`

The Pydantic model matching the wire protocol exactly (see above). `envelope.to_json()`
and `envelope.to_sse()` are convenience serializers; adapters use these (or a custom
`Serializer`, see below) internally.

## FastAPI adapter

```python
from eventloom.adapters.fastapi import to_sse_response, emitter_dependency
```

- **`to_sse_response(emitter, *, serializer=default_serializer, request=None, headers=None)`**
  — wraps an `EventEmitter` in a `StreamingResponse` over `text/event-stream`. Sets
  `Cache-Control`/`X-Accel-Buffering` headers so intermediary proxies don't buffer the
  stream. Pass `request=request` so the generator stops when the client disconnects
  instead of emitting into the void. Any exception raised while draining the emitter is
  converted into a `__stream_error__` envelope and sent before the connection closes.

- **`emitter_dependency(registry, group_id_from=None)`** — builds a FastAPI `Depends()`
  callable that produces a fresh `EventEmitter` per request:

  ```python
  get_emitter = emitter_dependency(registry, group_id_from=lambda req: req.path_params.get("user_id"))

  @app.get("/stream/{user_id}")
  async def stream(emitter: EventEmitter = Depends(get_emitter)):
      ...
      return to_sse_response(emitter)
  ```

## Pydantic v1 compatibility (`eventloom.contrib.pydantic_v1`)

`eventloom.core` requires Pydantic v2 (`StreamEnvelope`/`EventEmitter` always are, and
that never changes), but `StreamEnvelope.data` itself can be a **Pydantic-v1-style**
payload — `eventloom.core._compat` duck-types across the split (v2's
`.model_dump()`/`.model_validate()` vs. v1's `.dict()`/`.json()`/`.parse_obj()`), so a
schema registered from a v1 model works with `EventTypeRegistry`/`EventEmitter` exactly
like a v2 one, byte-identical on the wire.

`eventloom.contrib.pydantic_v1` is what actually produces those v1 payloads: a
partial-object-streaming toolkit for Pydantic v1 schemas, filling the gap left by
[`instructor`](https://python.useinstructor.com/) (which only supports Pydantic v2). It
works against a genuine standalone `pydantic<2` install, or — the common case, since
`eventloom` itself requires `pydantic>=2,<3` — Pydantic v2's bundled `pydantic.v1` compat
namespace; either way, models subclass `eventloom.contrib.pydantic_v1.BaseModel`.

```bash
pip install "eventloom[pydantic-v1]"   # pulls in openai + anthropic
```

```python
from eventloom.contrib.pydantic_v1 import BaseModel, stream_new_list_items
from eventloom.contrib.pydantic_v1.providers.openai import OpenAIStreamClient

class Insight(BaseModel):
    title: str
    detail: str

class InsightsBatch(BaseModel):
    insights: list[Insight] = []

client = OpenAIStreamClient()  # reads OPENAI_API_KEY from the environment

# Field-by-field partial streaming of a single object (pairs with strategy="merge"):
async for partial in client.stream(model="gpt-4o-mini", response_model=Insight, messages=[...]):
    ...  # partial.title / partial.detail fill in progressively

# Non-streaming, single validated result (mirrors instructor's `.create()`):
insight = await client.create(model="gpt-4o-mini", response_model=Insight, messages=[...])

# create_iterable()-equivalent for a growing list field (pairs with strategy="append"):
async for item in stream_new_list_items(
    client.stream(model="gpt-4o-mini", response_model=InsightsBatch, messages=[...]),
    get_list=lambda batch: batch.insights,
):
    ...  # each Insight, exactly once, as soon as it's complete
```

`AnthropicStreamClient` (`eventloom.contrib.pydantic_v1.providers.anthropic`) is a
drop-in alternative with the same interface. Every intermediate `.stream()` yield is a
cheap, unvalidated partial (`Model.construct()`, no `ValidationError`s mid-stream); once
the underlying token stream ends, one final, genuinely validated instance is appended
automatically (`validate_final=True`, the default) — pass `validate_final=False` for the
original, never-validates behavior. See
[`examples/dashboard_app_pydantic_v1.py`](examples/dashboard_app_pydantic_v1.py) for a
full FastAPI example — the same dashboard as `examples/dashboard_app.py`, rebuilt on this
instead of `instructor`, plus a demonstration of N concurrent instances of one event type
(distinct `id`s sharing a type).

## Testing your event-emitting code

`eventloom.testing.MockEmitter` is a drop-in `EventEmitter` that records every envelope,
so you can unit-test the logic that decides *what* to emit without an HTTP client or
event loop plumbing:

```python
from eventloom.testing import MockEmitter
from myapp.events import registry
from myapp.dashboard import run_dashboard_logic  # your code, takes an EventEmitter

async def test_dashboard_emits_chart_data():
    emitter = MockEmitter(registry)
    await run_dashboard_logic(emitter)

    assert emitter.emitted[0].type == "chart.data"
    assert emitter.emitted[0].data.labels == ["Q1", "Q2"]
    assert emitter.emitted_by_type("log.line")  # list of every log.line envelope, in order
```

## Extensibility

| What to override | How |
|---|---|
| Serialization format | Implement the `Serializer` protocol (`dumps(envelope) -> str`) and pass it to `to_sse_response(emitter, serializer=...)` |
| Merge strategy per event type | `registry.register(..., strategy=...)` |
| Transport | Write a new adapter (e.g. `adapters/websocket/`) that drains `EventEmitter.events()` into your transport — the `~20 line` FastAPI adapter (`adapters/fastapi/stream.py`) is the reference implementation |
| Envelope fields | Subclass `StreamEnvelope` to add custom metadata (auth context, tracing ids) |
| Validation / side effects on emit | Subclass `EventEmitter` and override `emit()` (see `eventloom.testing.MockEmitter` for a working example) |

Framework support beyond FastAPI (Flask, Django, raw ASGI/WSGI) is designed to be added
as new `eventloom.adapters.*` subpackages without touching `core` or requiring FastAPI as
a dependency — not shipped yet in v1 (see the project plan's build sequence).

## Error handling contract

If something fails mid-stream (after the HTTP response has already started, so a normal
error status code is no longer possible), `to_sse_response` emits a
`__stream_error__`-typed envelope as the last event on the stream:

```json
{"type": "__stream_error__", "id": "__stream_error__", "seq": 0, "data": {"message": "boom", "code": "RuntimeError"}, "strategy": "replace", "done": true, "ts": "..."}
```

`@akshilmy/eventloom-react`'s `<StreamView>` special-cases this type and routes it to the
`fallback` component rather than the registry.

## Development

```bash
cd python/eventloom
uv venv --python 3.12 .venv
uv pip install -e ".[test]" --python .venv/bin/python
.venv/bin/pytest
```

## License

MIT
