import { isStreamEnvelope, type StreamEnvelope } from "./envelope";

export interface StreamConnectionOptions {
  /** Override `fetch` (custom client, test double, polyfill). Defaults to `globalThis.fetch`. */
  fetchImpl?: typeof fetch;
  /**
   * Extra `fetch` options merged into every (re)connect request — headers,
   * `credentials`, an `AbortSignal` to compose with the connection's own, etc.
   * This is how auth tokens get attached; deliberately *not* done via native
   * `EventSource` (which can't set custom headers at all) — `StreamConnection`
   * uses `fetch` + manual SSE-frame parsing instead, which is also why the
   * server's optional `event:` line is ignored: routing is driven purely by
   * the `type` field inside the JSON body, matching the wire protocol's
   * single-source-of-truth design (plan section 2).
   */
  fetchOptions?: RequestInit;
  /** Reconnect automatically after a dropped/failed connection. Default `true`. */
  reconnect?: boolean;
  /**
   * Also reconnect after the stream ends *cleanly* (the server closed the
   * HTTP response normally — e.g. `eventloom.adapters.fastapi.to_sse_response`
   * closing the emitter once its producer finishes) rather than only after an
   * error. Default `false`: a clean close is treated as "the backend is done
   * emitting," not a failure to recover from — the common case for a
   * finite/one-shot stream (emit some events, mark `done`, close). Set this
   * to `true` for a backend that intentionally keeps closing and expects the
   * client to re-poll (rare — most "always on" dashboards should instead just
   * keep the emitter open server-side rather than relying on this).
   */
  reconnectOnComplete?: boolean;
  /** Initial reconnect delay in ms. Doubles on each consecutive failure. Default `1000`. */
  initialReconnectDelayMs?: number;
  /** Ceiling for the exponential backoff. Default `30000`. */
  maxReconnectDelayMs?: number;
  /** Called once the HTTP response has started successfully. */
  onOpen?: () => void;
  /** Called for a fetch/parse failure. Non-fatal unless `reconnect` is `false`. */
  onError?: (error: unknown) => void;
  /**
   * Called when the stream ends cleanly and won't be reconnected (i.e.
   * `reconnectOnComplete` is `false`, the default). Not called after
   * `disconnect()`, and not called if `reconnectOnComplete` is `true` (since
   * then it isn't actually done — it reconnects instead).
   */
  onComplete?: () => void;
}

/**
 * Connects to an eventloom SSE endpoint, parses each frame into a
 * `StreamEnvelope`, and invokes `onEnvelope` for each one — with
 * reconnect-with-backoff by default. Framework-agnostic; `@akshilmy/eventloom-react`'s
 * `useEventStream` wraps this in a hook.
 */
export class StreamConnection {
  private readonly fetchImpl: typeof fetch;
  private readonly reconnect: boolean;
  private readonly reconnectOnComplete: boolean;
  private readonly initialDelay: number;
  private readonly maxDelay: number;
  private abortController: AbortController | null = null;
  private closed = true;
  private currentDelay: number;

  constructor(
    private readonly url: string,
    private readonly onEnvelope: (envelope: StreamEnvelope) => void,
    private readonly options: StreamConnectionOptions = {}
  ) {
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
    this.reconnect = options.reconnect ?? true;
    this.reconnectOnComplete = options.reconnectOnComplete ?? false;
    this.initialDelay = options.initialReconnectDelayMs ?? 1000;
    this.maxDelay = options.maxReconnectDelayMs ?? 30000;
    this.currentDelay = this.initialDelay;
  }

  connect(): void {
    if (!this.closed) return; // already connected/connecting
    this.closed = false;
    void this.run();
  }

  disconnect(): void {
    this.closed = true;
    this.abortController?.abort();
    this.abortController = null;
  }

  private async run(): Promise<void> {
    while (!this.closed) {
      this.abortController = new AbortController();
      let endedCleanly = false;
      try {
        await this.streamOnce(this.abortController.signal);
        endedCleanly = true;
        this.currentDelay = this.initialDelay; // reset backoff after a clean session
      } catch (error) {
        if (this.closed) return; // disconnect() caused the abort; not a real error
        this.options.onError?.(error);
      }

      if (this.closed) return;

      // A clean end (the server closed the response normally — e.g. the
      // producer finished and the adapter closed the emitter) is completion,
      // not a failure — don't spin back up and replay the whole stream
      // unless the caller explicitly opted into that via `reconnectOnComplete`.
      if (endedCleanly && !this.reconnectOnComplete) {
        this.closed = true;
        this.options.onComplete?.();
        return;
      }

      if (!this.reconnect) return;

      await delay(this.currentDelay);
      this.currentDelay = Math.min(this.currentDelay * 2, this.maxDelay);
    }
  }

  private async streamOnce(signal: AbortSignal): Promise<void> {
    const response = await this.fetchImpl(this.url, {
      ...this.options.fetchOptions,
      signal,
      headers: { Accept: "text/event-stream", ...this.options.fetchOptions?.headers },
    });

    if (!response.ok || !response.body) {
      throw new Error(`eventloom: stream request failed with status ${response.status}`);
    }

    this.options.onOpen?.();

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE frames are separated by a blank line; a stream can end mid-frame,
        // so keep the trailing partial frame in `buffer` for the next chunk.
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) this.handleFrame(frame);
      }
      if (buffer.trim()) this.handleFrame(buffer);
    } finally {
      reader.releaseLock();
    }
  }

  private handleFrame(frame: string): void {
    const dataLines = frame
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice("data:".length).trimStart());
    if (dataLines.length === 0) return; // comment-only frame (e.g. SSE keep-alive `:`) — ignore

    const raw = dataLines.join("\n");
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch (error) {
      this.options.onError?.(new Error(`eventloom: malformed SSE data frame: ${raw}`));
      return;
    }

    if (!isStreamEnvelope(parsed)) {
      this.options.onError?.(new Error(`eventloom: received data frame is not a valid StreamEnvelope: ${raw}`));
      return;
    }

    this.onEnvelope(parsed);
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
