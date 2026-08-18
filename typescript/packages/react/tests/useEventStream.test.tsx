import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import type { StreamEnvelope } from "@akshilmy/eventloom-core";
import { useEventStream } from "../src/useEventStream";
import { createRegistry } from "../src/createRegistry";

function sseBody(frames: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let i = 0;
  return new ReadableStream({
    pull(controller) {
      if (i < frames.length) {
        controller.enqueue(encoder.encode(frames[i]));
        i++;
      } else {
        controller.close();
      }
    },
  });
}

function envelopeFrame(overrides: Partial<StreamEnvelope>): string {
  const full: StreamEnvelope = {
    type: "chart.data",
    id: "id-1",
    seq: 0,
    data: {},
    strategy: "replace",
    done: false,
    ts: "2026-08-18T00:00:00Z",
    ...overrides,
  };
  return `data: ${JSON.stringify(full)}\n\n`;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useEventStream", () => {
  it("connects, applies envelopes through the store, and exposes a snapshot", async () => {
    const frames = [
      envelopeFrame({ id: "chart-1", seq: 0, data: { labels: ["Q1"] }, strategy: "replace", done: true }),
      envelopeFrame({ id: "log-1", type: "log.line", seq: 0, data: { text: "a" }, strategy: "append" }),
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(sseBody(frames), { status: 200 }))
    );

    const { result, unmount } = renderHook(() => useEventStream("/stream/dashboard", { reconnect: false }));

    await waitFor(() => expect(result.current.events).toHaveLength(2));
    // The mocked stream is finite and ends cleanly after these two frames, so
    // status settles to "closed" (not "open") — see the dedicated
    // "does not repeatedly refetch..." test below for why that matters.
    expect(result.current.status).toBe("closed");
    const chart = result.current.events.find((e) => e.id === "chart-1");
    expect(chart?.data).toEqual({ labels: ["Q1"] });

    unmount();
  });

  it("applies a registry's per-type strategy override instead of the backend's declared one", async () => {
    // Backend declares "replace", but the frontend registration overrides to "merge".
    const frames = [
      envelopeFrame({ id: "p1", type: "user.partial", seq: 0, data: { name: "Ada" }, strategy: "replace" }),
      envelopeFrame({ id: "p1", type: "user.partial", seq: 1, data: { bio: "Mathematician" }, strategy: "replace" }),
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(sseBody(frames), { status: 200 }))
    );

    const registry = createRegistry().register("user.partial", {
      renderer: () => null,
      strategy: "merge",
    });

    const { result, unmount } = renderHook(() =>
      useEventStream("/stream/dashboard", { registry, reconnect: false })
    );

    await waitFor(() => expect(result.current.events).toHaveLength(1));
    expect(result.current.events[0]?.data).toEqual({ name: "Ada", bio: "Mathematician" });

    unmount();
  });

  it("does not repeatedly refetch after a finite stream (emit-then-close) finishes cleanly", async () => {
    // Regression test: a backend that emits some events, marks done, and
    // closes (exactly what python/eventloom's `to_sse_response` does once its
    // `run` producer finishes) must not be treated as a dropped connection to
    // recover from — the hook should settle into "closed", not loop forever
    // re-fetching and re-applying the same events.
    const frames = [envelopeFrame({ id: "chart-1", seq: 0, data: { labels: ["Q1"] }, done: true })];
    const fetchMock = vi.fn().mockResolvedValue(new Response(sseBody(frames), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const { result, unmount } = renderHook(() => useEventStream("/stream/dashboard"));

    await waitFor(() => expect(result.current.status).toBe("closed"));
    expect(result.current.events).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledOnce();

    // Give it a beat — a buggy implementation would have already issued a
    // second (or third, ...) fetch by now.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(fetchMock).toHaveBeenCalledOnce();

    unmount();
  });

  it("surfaces connection errors via status/error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 500 })));

    const { result, unmount } = renderHook(() => useEventStream("/stream/dashboard", { reconnect: false }));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error).toBeInstanceOf(Error);

    unmount();
  });

  it("disconnects on unmount", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(sseBody([]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const { unmount } = renderHook(() => useEventStream("/stream/dashboard", { reconnect: false }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    unmount();

    // No assertion beyond "doesn't throw" — disconnect() aborts the in-flight
    // fetch's AbortSignal; jsdom doesn't give us an easy hook to assert on
    // that directly, but StreamConnection's own tests cover abort behavior.
  });
});
