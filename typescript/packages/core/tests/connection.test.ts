import { afterEach, describe, expect, it, vi } from "vitest";
import { StreamConnection } from "../src/connection";
import type { StreamEnvelope } from "../src/envelope";

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
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("StreamConnection", () => {
  it("parses SSE frames into envelopes in order and calls onOpen", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(new Response(sseBody([envelopeFrame({ seq: 0 }), envelopeFrame({ seq: 1 })]), { status: 200 }));

    const received: StreamEnvelope[] = [];
    const onOpen = vi.fn();
    const conn = new StreamConnection("http://test/stream", (e) => received.push(e), {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      onOpen,
      reconnect: false,
    });
    conn.connect();

    await vi.waitFor(() => expect(received).toHaveLength(2));
    expect(onOpen).toHaveBeenCalledOnce();
    expect(received.map((e) => e.seq)).toEqual([0, 1]);
    conn.disconnect();
  });

  it("splits a data frame across multiple fetch chunks correctly", async () => {
    const frame = envelopeFrame({ seq: 0 });
    const mid = Math.floor(frame.length / 2);
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(frame.slice(0, mid)));
        controller.enqueue(encoder.encode(frame.slice(mid)));
        controller.close();
      },
    });
    const fetchImpl = vi.fn().mockResolvedValue(new Response(body, { status: 200 }));

    const received: StreamEnvelope[] = [];
    const conn = new StreamConnection("http://test/stream", (e) => received.push(e), {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      reconnect: false,
    });
    conn.connect();

    await vi.waitFor(() => expect(received).toHaveLength(1));
    conn.disconnect();
  });

  it("ignores the SSE event: line and routes purely on the JSON type field", async () => {
    const envelope: StreamEnvelope = {
      type: "log.line",
      id: "log-1",
      seq: 0,
      data: { text: "hi" },
      strategy: "append",
      done: false,
      ts: "t",
    };
    const frame = `event: log.line\ndata: ${JSON.stringify(envelope)}\n\n`;
    const fetchImpl = vi.fn().mockResolvedValue(new Response(sseBody([frame]), { status: 200 }));

    const received: StreamEnvelope[] = [];
    const conn = new StreamConnection("http://test/stream", (e) => received.push(e), {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      reconnect: false,
    });
    conn.connect();

    await vi.waitFor(() => expect(received).toHaveLength(1));
    expect(received[0]?.type).toBe("log.line");
    conn.disconnect();
  });

  it("reports malformed JSON data frames via onError without dropping subsequent valid ones", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(new Response(sseBody(["data: not-json\n\n", envelopeFrame({ seq: 0 })]), { status: 200 }));

    const received: StreamEnvelope[] = [];
    const onError = vi.fn();
    const conn = new StreamConnection("http://test/stream", (e) => received.push(e), {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      onError,
      reconnect: false,
    });
    conn.connect();

    await vi.waitFor(() => expect(received).toHaveLength(1));
    expect(onError).toHaveBeenCalledOnce();
    conn.disconnect();
  });

  it("reports a non-ok HTTP response via onError", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 500 }));
    const onError = vi.fn();
    const conn = new StreamConnection("http://test/stream", () => {}, {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      onError,
      reconnect: false,
    });
    conn.connect();

    await vi.waitFor(() => expect(onError).toHaveBeenCalledOnce());
    conn.disconnect();
  });

  it("passes fetchOptions (headers/credentials) through to every request", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(sseBody([]), { status: 200 }));
    const conn = new StreamConnection("http://test/stream", () => {}, {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      fetchOptions: { headers: { Authorization: "Bearer token" }, credentials: "include" },
      reconnect: false,
    });
    conn.connect();

    await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalledOnce());
    const [, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer token");
    expect(init.credentials).toBe("include");
    conn.disconnect();
  });

  it("does not reconnect after the stream ends cleanly (default reconnectOnComplete: false)", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn().mockResolvedValue(new Response(sseBody([envelopeFrame({ seq: 0 })]), { status: 200 }));
    const onComplete = vi.fn();
    const received: StreamEnvelope[] = [];

    const conn = new StreamConnection("http://test/stream", (e) => received.push(e), {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      initialReconnectDelayMs: 100,
      onComplete,
    });
    conn.connect();

    await vi.advanceTimersByTimeAsync(0);
    expect(received).toHaveLength(1);
    expect(onComplete).toHaveBeenCalledOnce();

    // Even after plenty of time, no reconnect attempt — the stream finished, it didn't fail.
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it("does reconnect after a clean end when reconnectOnComplete is true", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn().mockResolvedValue(new Response(sseBody([envelopeFrame({ seq: 0 })]), { status: 200 }));
    const onComplete = vi.fn();

    const conn = new StreamConnection("http://test/stream", () => {}, {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      initialReconnectDelayMs: 100,
      reconnectOnComplete: true,
      onComplete,
    });
    conn.connect();

    await vi.advanceTimersByTimeAsync(0);
    expect(fetchImpl).toHaveBeenCalledOnce();

    await vi.advanceTimersByTimeAsync(150);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(onComplete).not.toHaveBeenCalled();

    conn.disconnect();
  });

  it("still reconnects after an actual error (non-ok response), unaffected by the clean-end change", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 500 }));
    const onError = vi.fn();
    const onComplete = vi.fn();

    const conn = new StreamConnection("http://test/stream", () => {}, {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      initialReconnectDelayMs: 100,
      onError,
      onComplete,
    });
    conn.connect();

    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(150);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(onError).toHaveBeenCalledTimes(2);
    expect(onComplete).not.toHaveBeenCalled();

    conn.disconnect();
  });

  it("reconnects with exponential backoff after a failed attempt", async () => {
    vi.useFakeTimers();
    let call = 0;
    const fetchImpl = vi.fn().mockImplementation(async () => {
      call += 1;
      if (call === 1) return new Response(null, { status: 500 });
      return new Response(sseBody([envelopeFrame({ seq: 0 })]), { status: 200 });
    });

    const received: StreamEnvelope[] = [];
    const onError = vi.fn();
    const conn = new StreamConnection("http://test/stream", (e) => received.push(e), {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      onError,
      initialReconnectDelayMs: 100,
    });
    conn.connect();

    await vi.advanceTimersByTimeAsync(0);
    expect(onError).toHaveBeenCalledOnce();
    expect(fetchImpl).toHaveBeenCalledOnce();

    await vi.advanceTimersByTimeAsync(150);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(received).toHaveLength(1);

    conn.disconnect();
  });

  it("does not reconnect after disconnect() even if the connection later fails", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 500 }));
    const conn = new StreamConnection("http://test/stream", () => {}, {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      initialReconnectDelayMs: 100,
    });
    conn.connect();
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchImpl).toHaveBeenCalledOnce();

    conn.disconnect();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetchImpl).toHaveBeenCalledOnce(); // no reconnect attempt after disconnect
  });

  it("connect() is a no-op if already connected", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(sseBody([]), { status: 200 }));
    const conn = new StreamConnection("http://test/stream", () => {}, {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      reconnect: false,
    });
    conn.connect();
    conn.connect();
    await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalledOnce());
    conn.disconnect();
  });
});
