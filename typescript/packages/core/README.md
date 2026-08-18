# @akshilmy/eventloom-core

Framework-agnostic engine for [eventloom](https://github.com/akshilmy/eventloom): wire-protocol
types, an SSE connection with reconnect/backoff, per-`id` merge/replace/append logic, and a
type-accumulating component registry. Zero React/Vue/framework dependency — pairs with
[`@akshilmy/eventloom-react`](https://www.npmjs.com/package/@akshilmy/eventloom-react) (first-class)
or your own adapter (Vue, vanilla JS). Pairs on the backend with the Python
[`eventloom`](https://pypi.org/project/eventloom/) package, but the wire protocol is
language-agnostic — any backend that emits matching JSON over SSE works.

## Install

```bash
npm install @akshilmy/eventloom-core
```

Most apps want [`@akshilmy/eventloom-react`](https://www.npmjs.com/package/@akshilmy/eventloom-react)
instead, which depends on this package and adds React bindings. Install `core` directly only if
you're writing your own framework adapter or consuming the stream from vanilla JS.

## Quickstart (framework-agnostic)

```ts
import { StreamConnection, EventStore } from "@akshilmy/eventloom-core";

const store = new EventStore();

const connection = new StreamConnection(
  "/stream/dashboard",
  (envelope) => {
    store.apply(envelope); // combines with any prior state for envelope.id per its strategy
    render(store.snapshot()); // your own render function
  },
  {
    onError: (err) => console.error("stream error:", err),
  }
);

connection.connect();
// later: connection.disconnect();
```

## Wire protocol

```ts
interface StreamEnvelope<T = unknown> {
  type: string; // event type, e.g. "chart.data" — routes to a component
  id: string; // groups events belonging to the same logical "thing"
  seq: number; // monotonic sequence number within this id
  data: T; // event-specific payload
  strategy: "replace" | "merge" | "append";
  done: boolean; // true if this is the final event for this id
  ts: string; // ISO timestamp
}
```

This is a TypeScript `interface`, not a class — envelopes arrive as plain parsed JSON. Use
`isStreamEnvelope(value)` to runtime-check an unknown value (this is what `StreamConnection` uses
internally to reject malformed frames instead of crashing).

## `EventStore` — merge/replace/append logic

```ts
const store = new EventStore();
store.apply(envelope); // combine one envelope into the store
store.get(id); // -> EventSnapshot | undefined, current state for one id
store.snapshot(); // -> EventSnapshot[], every id's current state
store.clear();
```

Per `envelope.strategy`:

| Strategy | Behavior | `data` shape you get back from `get`/`snapshot` |
|---|---|---|
| `replace` | New data fully replaces old. | Whatever the latest envelope's `data` was. |
| `merge` | Shallow-merges new fields into the existing object (`{...existing, ...incoming}`). | The accumulated object. |
| `append` | Pushes into an array. | **An array of every item emitted for that `id` so far** — not a single item. A renderer for an `append`-strategy type should expect `data: T[]`, e.g. a log viewer rendering every line, not just the latest one. |

`EventStore` also defensively ignores a stale/duplicate envelope (`seq <= last applied seq for
that id`) — cheap insurance against a reconnect replaying an already-applied event; SSE already
guarantees in-order delivery per connection, so this rarely triggers in practice.

## `StreamConnection` — transport

```ts
const connection = new StreamConnection(url, onEnvelope, {
  fetchOptions: { headers: { Authorization: "Bearer ..." }, credentials: "include" },
  reconnect: true, // default true — reconnect after an error
  reconnectOnComplete: false, // default false — do NOT reconnect after a clean, intentional close
  initialReconnectDelayMs: 1000, // default
  maxReconnectDelayMs: 30000, // default; backoff doubles each failed attempt
  onOpen: () => {},
  onError: (err) => {},
  onComplete: () => {}, // fires once, when the stream ends cleanly and won't reconnect
});
connection.connect();
connection.disconnect();
```

**Clean completion vs. error — these reconnect differently, on purpose.** If the backend closes
the HTTP response normally (e.g. `to_sse_response`'s producer finishes and the adapter closes the
emitter), that's treated as *done*, not a failure: `onComplete` fires once and the connection does
not retry, even though `reconnect` defaults to `true`. Only an actual error (non-2xx response,
network failure) triggers the reconnect-with-backoff loop. This matters for the common "emit some
events then close" shape (mirrors how most streamed responses work) — without this distinction,
every finite stream would get re-fetched and replayed forever the moment it finished, which is
exactly the failure mode this default avoids. If you're building a backend that intentionally
expects the client to keep re-polling after every close, set `reconnectOnComplete: true`.

Built on `fetch` + manual SSE-frame parsing rather than the native `EventSource` API — deliberately,
for two reasons:

1. **`EventSource` can't set custom headers**, so there's no way to attach an `Authorization`
   header to it. `fetchOptions` solves auth/credentials cleanly.
2. **Routing is driven purely by the JSON `type` field**, not any SSE `event:` line. A backend may
   still send `event: <type>` (the Python adapter does, for tooling like `curl`/devtools), but
   `StreamConnection` ignores it — per the wire protocol's design (see the project's wire-protocol
   section), the JSON body is the single source of truth, so switching between languages/adapters
   that include or omit `event:` never changes client behavior.

## `ComponentRegistry` — the framework-agnostic base

```ts
import { ComponentRegistry } from "@akshilmy/eventloom-core";

const registry = new ComponentRegistry()
  .register("chart.data", { renderer: myChartRenderFn })
  .register("log.line", { renderer: myLogRenderFn, strategy: "append" });

registry.get("chart.data"); // -> { renderer: myChartRenderFn }
registry.has("chart.data"); // -> true
registry.types(); // -> ["chart.data", "log.line"]
```

`renderer` is deliberately typed `unknown` here — core doesn't know what a "renderer" means.
`@akshilmy/eventloom-react`'s `createRegistry()` wraps this with a React-aware `register()` that
requires `renderer` to be a `ComponentType<{ data: T }>`, so passing a component with the wrong
prop type for the event type you're registering is a **compile error**. Writing a Vue or vanilla
adapter means doing the same narrowing for whatever "renderer" means in that context — `core`
itself only needs to store the config and accumulate the type-level `{ type -> payload }` map.

A registration's `strategy` field overrides the backend's declared strategy for that type, if set
— useful when a frontend wants different combine semantics than the backend author chose.

## Extensibility

| What to override | How |
|---|---|
| Reconnect/backoff behavior | `StreamConnectionOptions` — `reconnect`, `reconnectOnComplete`, `initialReconnectDelayMs`, `maxReconnectDelayMs` |
| Auth headers, credentials | `StreamConnectionOptions.fetchOptions` |
| Transport (SSE vs WebSocket later) | Implement your own class with the same `connect()`/`disconnect()`/envelope-callback shape and swap it in |
| Merge strategy (frontend override of backend default) | `registry.register(type, { renderer, strategy: "..." })`, then apply the override before calling `store.apply()` (see `@akshilmy/eventloom-react`'s `useEventStream` for the reference implementation) |
| Layout/ordering of rendered events | Don't use a higher-level component like `<StreamView>` — drive `StreamConnection` + `EventStore` directly and render `store.snapshot()` however you like |

## Development

```bash
cd typescript
npm install
npm run build --workspace=@akshilmy/eventloom-core
npm run test --workspace=@akshilmy/eventloom-core
npm run typecheck --workspace=@akshilmy/eventloom-core
```

## License

MIT
