# @akshilmy/eventloom-react

React bindings for [eventloom](https://github.com/akshilmy/eventloom): a `useEventStream` hook, a
`<StreamView>` component, and a type-safe registry that maps backend event types to your
components. Built on [`@akshilmy/eventloom-core`](https://www.npmjs.com/package/@akshilmy/eventloom-core)
(SSE connection + merge logic); pairs with the Python [`eventloom`](https://pypi.org/project/eventloom/)
+ [`eventloom[fastapi]`](https://pypi.org/project/eventloom/) packages on the backend, but works
against any backend that emits the same [wire protocol](#wire-protocol) over SSE.

- No LLM/agent required, fully deterministic: the backend decides what events mean, you decide
  what component renders each one.
- Type safety: registering the wrong component for an event type is a compile error.
- Discrete and partial events are both first-class — merge strategy is chosen per event type.

## Install

```bash
npm install @akshilmy/eventloom-react
```

`@akshilmy/eventloom-core` is a dependency and installs automatically. Requires React 18+.

## Quickstart

**1. Define a component per event type.** Each one receives `{ data, done, id }`:

```tsx
// components.tsx
interface ChartData {
  labels: string[];
  values: number[];
}

function ChartWidget({ data, done }: { data: ChartData; done: boolean; id: string }) {
  return <BarChart labels={data.labels} values={data.values} loading={!done} />;
}

interface UserProfile {
  name?: string;
  bio?: string;
}

function UserCard({ data }: { data: UserProfile; done: boolean; id: string }) {
  return (
    <div>
      <h3>{data.name ?? "Loading…"}</h3>
      <p>{data.bio ?? ""}</p>
    </div>
  );
}

// "append" strategy accumulates into an array — see the note under EventStore
// in @akshilmy/eventloom-core's README. Render every item, not just the latest.
function LogViewer({ data }: { data: Array<{ text: string }>; done: boolean; id: string }) {
  return (
    <pre>
      {data.map((line, i) => (
        <div key={i}>{line.text}</div>
      ))}
    </pre>
  );
}
```

**2. Build a registry mapping event type -> component:**

```tsx
import { createRegistry } from "@akshilmy/eventloom-react";

const registry = createRegistry()
  .register("chart.data", { renderer: ChartWidget })
  .register("user.partial", { renderer: UserCard, strategy: "merge" })
  .register("log.line", { renderer: LogViewer, strategy: "append" });
```

**3. Point `<StreamView>` at your backend endpoint:**

```tsx
import { StreamView } from "@akshilmy/eventloom-react";

function Dashboard() {
  return <StreamView endpoint="/stream/dashboard" registry={registry} />;
}
```

That's the whole integration. Every envelope your backend emits on `/stream/dashboard` gets
combined per its merge strategy and routed to the matching component automatically.

## Type safety

```tsx
const BadWidget: React.FC<{ data: { wrongShape: true }; done: boolean; id: string }> = () => null;

createRegistry().register("chart.data", { renderer: BadWidget });
//                                                    ~~~~~~~~~
// Type error if you also pin the expected payload type:
createRegistry().register<"chart.data", ChartData>("chart.data", { renderer: BadWidget });
// ❌ Type 'FC<{ data: { wrongShape: true }; ... }>' is not assignable to
//    type 'ComponentType<EventComponentProps<ChartData>>'
```

Auto-inference (no explicit generics needed) works for the common case — passing a component
with a concrete `data` prop type just infers the payload type from it. Pin `<Type, Payload>`
explicitly when you want the compiler to check a renderer against a payload type you maintain by
hand (matching your backend's Pydantic model) or, later, generate via the optional codegen bridge
described in the project plan — not required for v1, but the registry API is designed to support it
without changes once it exists.

## `useEventStream` — for custom layouts

Use this instead of `<StreamView>` when you need custom layout, filtering, or ordering:

```tsx
import { useEventStream } from "@akshilmy/eventloom-react";

function Dashboard() {
  const { events, status, error } = useEventStream("/stream/dashboard", { registry });

  if (status === "error") return <ErrorBanner error={error} />;

  return (
    <div className="grid grid-cols-2">
      {events.map((event) => {
        const config = registry.get(event.type);
        if (!config) return null;
        const Component = config.renderer;
        return <Component key={event.id} id={event.id} data={event.data} done={event.done} />;
      })}
    </div>
  );
}
```

`useEventStream(endpoint, options)` returns:

- `events: EventSnapshot[]` — every `id`'s current combined state.
- `status: "connecting" | "open" | "closed" | "error"`. `"closed"` means the backend ended the
  stream normally and it won't be retried (see [Reconnection](#reconnection)) — a finite stream
  (emit some events, mark `done`, close) settles here, not stuck on `"open"` forever.
- `error: unknown` — the last connection error, if `status === "error"`.

`options` (all optional): `registry` (for per-type strategy overrides), `fetchOptions` (headers,
credentials — see [auth](#auth--credentials)), `reconnect`, `reconnectOnComplete`,
`initialReconnectDelayMs`, `maxReconnectDelayMs`, `onError`, `onComplete`.

Only `endpoint` re-triggers a reconnect; other options are read fresh per event but don't tear
down and rebuild the connection on every render — change `endpoint` (or unmount/remount) to force
a fresh connection with new options.

## Error handling

If the backend's stream fails mid-way (see the Python package's `to_sse_response` docs), it sends
a built-in `__stream_error__`-typed envelope as the last event. Apps never register that type
themselves, so it always falls through to `<StreamView>`'s `fallback`:

```tsx
import { STREAM_ERROR_TYPE, type StreamErrorData } from "@akshilmy/eventloom-react";

function Fallback({ data, id }: { data: unknown; done: boolean; id: string }) {
  if (id === STREAM_ERROR_TYPE) {
    const error = data as StreamErrorData;
    return <ErrorBanner message={error.message} code={error.code} />;
  }
  return <UnknownEventCard />; // any other unregistered type
}

<StreamView endpoint="/stream/dashboard" registry={registry} fallback={Fallback} />;
```

A connection-level failure (can't reach the server at all, non-2xx response) surfaces instead via
`useEventStream`'s `status`/`error` (or `<StreamView>`'s `onError` prop, forwarded straight
through) — that's a different failure mode than a mid-stream `__stream_error__` envelope, since the
latter requires the HTTP response to have started successfully first.

## Auth / credentials

`EventSource` (the browser's native SSE client) can't set custom headers — this package uses
`fetch` internally instead specifically so you can:

```tsx
useEventStream("/stream/dashboard", {
  fetchOptions: {
    headers: { Authorization: `Bearer ${token}` },
    credentials: "include", // send cookies
  },
});
```

## Reconnection

On a dropped or failed connection (network error, non-2xx response), `useEventStream`/`<StreamView>`
reconnect automatically with exponential backoff (1s → 2s → 4s → ... capped at 30s by default).
Disable with `reconnect: false`, or tune `initialReconnectDelayMs`/`maxReconnectDelayMs`.

**A clean close (the backend finished and closed the response normally) is treated as
completion, not a failure — it does *not* reconnect by default,** even though `reconnect` defaults
to `true`. This matters for the common shape of "emit some events, mark the last one `done`, close
the connection" (exactly what `eventloom`'s FastAPI adapter does once its producer finishes):
without this distinction, every finite stream would get silently re-fetched and replayed in a loop
the moment it finished. `status` becomes `"closed"` and `onComplete` fires once. If your backend
instead expects the client to keep re-polling after every close, opt into the old behavior with
`reconnectOnComplete: true`.

## Extensibility

| What to override | How |
|---|---|
| Which component renders which event type | `registry.register(type, { renderer })` |
| Merge strategy (frontend override of backend default) | `{ renderer, strategy: "..." }` in registration |
| Unregistered event fallback | `<StreamView fallback={UnknownEventCard} />` |
| Reconnect/backoff behavior | `useEventStream`/`<StreamView>` options (`reconnect`, `reconnectOnComplete`, `initialReconnectDelayMs`, `maxReconnectDelayMs`), or use `@akshilmy/eventloom-core`'s `StreamConnection` directly for full control |
| Transport (SSE vs WebSocket later) | Swap the underlying `StreamConnection` — not yet pluggable at the hook level in v1; use `@akshilmy/eventloom-core` directly if you need this today |
| Layout/ordering of rendered events | Don't use `<StreamView>` — use `useEventStream` directly and render however you like |
| Auth headers, credentials | `fetchOptions` (see above) |

## Development

```bash
cd typescript
npm install
npm run build --workspace=@akshilmy/eventloom-core   # react depends on core's build output
npm run build --workspace=@akshilmy/eventloom-react
npm run test --workspace=@akshilmy/eventloom-react
npm run typecheck --workspace=@akshilmy/eventloom-react
```

## License

MIT
