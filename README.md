# eventloom

A generalized, deterministic event-streaming system for backend-to-frontend UIs. Any backend
framework emits typed events; the frontend renders them by mapping event types to components.
No LLM/agent required — the backend decides what happened, the frontend decides how to show it.

Two independently-publishable packages implementing one frozen [wire protocol](#wire-protocol):

| Package | Registry | What it is |
|---|---|---|
| [`eventloom`](python/eventloom) | PyPI | Framework-agnostic core (envelope, registry, emitter) + first-class FastAPI adapter |
| [`@akshilmy/eventloom-core`](typescript/packages/core) | npm | Framework-agnostic engine (SSE connection, merge/replace/append store, component registry) |
| [`@akshilmy/eventloom-react`](typescript/packages/react) | npm | React adapter on top of `eventloom-core`: `useEventStream`, `<StreamView>`, typed registry |

Each package README is the real documentation — install instructions, full API reference, and
copy-pasteable examples for developers consuming it standalone from PyPI/npm:

- **[python/eventloom/README.md](python/eventloom/README.md)**
- **[typescript/packages/core/README.md](typescript/packages/core/README.md)**
- **[typescript/packages/react/README.md](typescript/packages/react/README.md)**

This file covers what ties the two languages together and how to run the whole thing locally.

## Wire protocol

The one contract both packages implement — this is what lets you swap either side (a Go backend,
a Svelte frontend) without touching the other:

```ts
interface StreamEnvelope<T = unknown> {
  type: string; // event type, e.g. "chart.data" — routes to a component
  id: string; // groups events belonging to the same logical "thing"
  seq: number; // monotonic sequence number within this id
  data: T; // event-specific payload
  strategy: "replace" | "merge" | "append"; // how this event combines with prior ones sharing id
  done: boolean; // true if this is the final event for this id
  ts: string; // ISO timestamp
}
```

One JSON object per SSE `data:` line. `strategy` is decided by the backend's event registration,
not hardcoded on the frontend. See `eventloom-project-plan.md` section 2 for the full rationale
this was designed against.

**A subtlety worth knowing if you write your own client or adapter:** for `strategy: "merge"`,
the Python emitter serializes only the fields you actually set on that emit call (Pydantic's
`exclude_unset`), not the payload schema's full field set with `null` defaults filled in. A naive
serializer that dumps every field would cause a later partial update's unset fields to silently
overwrite an earlier update's already-set fields once the frontend does `{...existing, ...incoming}`.
See `eventloom.core.envelope.StreamEnvelope.to_json()`'s docstring for the mechanics, and its test
(`test_merge_strategy_excludes_unset_fields_so_partials_dont_clobber_each_other`) for the exact
failure mode this avoids — this was caught by running the example end-to-end, not by inspection.

## Run the full stack locally

```bash
# 1. Python backend (terminal 1)
cd python/eventloom
uv venv --python 3.12 .venv
uv pip install -e ".[test,fastapi]" --python .venv/bin/python
uv pip install uvicorn --python .venv/bin/python
.venv/bin/python examples/dashboard_app.py   # serves http://localhost:8000/stream/dashboard

# 2. React frontend (terminal 2)
cd typescript
npm install
npm run build --workspace=@akshilmy/eventloom-core
npm run build --workspace=@akshilmy/eventloom-react
cd examples/react-dashboard
npm run dev   # http://localhost:5173, calls http://localhost:8000 directly (CORS, no dev proxy)
```

Open `http://localhost:5173` (not `:8000` — that's the raw backend, only meaningful via `curl`
or as a fetch target) — you'll see a bar chart (`replace` strategy), a profile card filling in
field-by-field (`merge` strategy), and a scrolling activity log (`append` strategy), all driven by
one Python endpoint emitting three different event types.

## Troubleshooting

**The page loads but nothing ever renders, and the Network tab shows repeated failed/`500`
requests to the stream endpoint.** If you're using a same-origin dev-server proxy in front of the
backend (Vite's `server.proxy`, webpack-dev-server, etc.) instead of the direct-cross-origin+CORS
setup the example uses, check whether an unrelated cookie is the culprit: browsers scope cookies
to the bare domain (`localhost`) regardless of port, so a large session cookie some *other* local
app set for `localhost` gets attached to same-origin requests through the proxy too. A sufficiently
large one can make some dev proxies (Vite's included) fail the request outright with an opaque
`500` before it ever reaches the backend — even though the exact same request works fine with
`curl` (which doesn't send browser cookies) or straight to the backend's own port. Confirm by
diffing a `curl` to the backend's port directly against one through the proxy with a large
`Cookie:` header added; if only the proxied one fails, that's the issue. The example app sidesteps
this entirely by talking to the backend cross-origin (see `dashboard_app.py`'s `CORSMiddleware`
and `examples/react-dashboard/vite.config.ts`) rather than through a proxy — `StreamConnection`
doesn't send credentials by default, so no cookies cross the origin boundary either way.

## Verifying changes to the wire protocol

Because the contract is what actually matters, `typescript/packages/core`'s `StreamConnection` was
verified directly against a live Python server (not just against mocked fixtures) — connect
`@akshilmy/eventloom-core`'s built output to `python/eventloom/examples/dashboard_app.py` and
confirm the `EventStore` snapshot matches expectations for all three strategies. If you change
`StreamEnvelope` on either side, re-run that check before assuming the two packages still agree.

## Test suites

```bash
# Python: 24 tests (envelope, registry, emitter, FastAPI adapter, MockEmitter)
cd python/eventloom && .venv/bin/pytest -v

# TypeScript: 40 tests (core: envelope/registry/store/connection; react: hook/component)
cd typescript && npm run test
cd typescript && npm run typecheck   # includes a dedicated @ts-expect-error check that a
                                      # mismatched renderer for a pinned payload type fails to compile
```

## What's deliberately not built yet

Per the project plan's build sequence (section 6), Flask/Django adapters, a WebSocket transport,
and the Pydantic-to-TypeScript codegen bridge are **not implemented** — they're each addable later
without touching `core` in either language (that's the whole point of the core/adapter split), but
building them now would be speculative. Ship v1, get a second real consumer, then revisit.

## Project plan

The full design rationale (principles, extensibility tables, open decisions) lives in
[`eventloom-project-plan.md`](../eventloom-project-plan.md) (one level up from this package tree)
— this README is the "how do I actually run this" companion to it.

## License

MIT
