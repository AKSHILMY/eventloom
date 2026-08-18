import { useEffect, useRef, useState } from "react";
import { EventStore, StreamConnection } from "@akshilmy/eventloom-core";
import type { EventSnapshot, StreamEnvelope } from "@akshilmy/eventloom-core";
import type { TypedComponentRegistry } from "./createRegistry";

export interface UseEventStreamOptions {
  /** If a registration sets `strategy`, it overrides the backend's declared strategy for that type. */
  registry?: TypedComponentRegistry<Record<string, unknown>>;
  /** Passed through to the underlying `fetch` call on every (re)connect — headers, credentials, etc. */
  fetchOptions?: RequestInit;
  /** Reconnect automatically after a dropped/failed connection. Default `true`. */
  reconnect?: boolean;
  /**
   * Also reconnect after the stream ends *cleanly* (backend closed normally),
   * instead of treating that as completion. Default `false` — see
   * `@akshilmy/eventloom-core`'s `StreamConnectionOptions.reconnectOnComplete`
   * for when you'd actually want `true`.
   */
  reconnectOnComplete?: boolean;
  initialReconnectDelayMs?: number;
  maxReconnectDelayMs?: number;
  /** Called for every connection error (in addition to `status`/`error` being updated). */
  onError?: (error: unknown) => void;
  /** Called once the stream finishes cleanly and won't reconnect (`status` becomes `"closed"`). */
  onComplete?: () => void;
}

export type StreamStatus = "connecting" | "open" | "closed" | "error";

export interface UseEventStreamResult {
  /** Combined, per-`id` state — replace/merge/append already applied. */
  events: EventSnapshot[];
  status: StreamStatus;
  error: unknown;
}

/**
 * Connects to an eventloom SSE endpoint and returns the live, combined event
 * state. For simple layouts, `<StreamView>` wraps this and renders directly
 * from a registry; use this hook instead when you need custom layout,
 * filtering, or ordering (plan section 4.4).
 */
export function useEventStream(endpoint: string, options: UseEventStreamOptions = {}): UseEventStreamResult {
  const [events, setEvents] = useState<EventSnapshot[]>([]);
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const [error, setError] = useState<unknown>(null);

  // Read fresh on every envelope without re-running the connect effect for
  // every render — only `endpoint` re-triggers a (re)connect. To reconnect
  // with new `fetchOptions`/etc., change `endpoint` or unmount/remount.
  const optionsRef = useRef(options);
  optionsRef.current = options;

  useEffect(() => {
    const store = new EventStore();
    setEvents([]);
    setStatus("connecting");
    setError(null);

    const handleEnvelope = (envelope: StreamEnvelope) => {
      const strategyOverride = optionsRef.current.registry?.get(envelope.type)?.strategy;
      store.apply(strategyOverride ? { ...envelope, strategy: strategyOverride } : envelope);
      setEvents(store.snapshot());
      setStatus("open");
    };

    const connection = new StreamConnection(endpoint, handleEnvelope, {
      fetchOptions: optionsRef.current.fetchOptions,
      reconnect: optionsRef.current.reconnect,
      reconnectOnComplete: optionsRef.current.reconnectOnComplete,
      initialReconnectDelayMs: optionsRef.current.initialReconnectDelayMs,
      maxReconnectDelayMs: optionsRef.current.maxReconnectDelayMs,
      onOpen: () => setStatus("open"),
      onError: (err) => {
        setStatus("error");
        setError(err);
        optionsRef.current.onError?.(err);
      },
      onComplete: () => {
        setStatus("closed");
        optionsRef.current.onComplete?.();
      },
    });

    connection.connect();
    return () => connection.disconnect();
  }, [endpoint]);

  return { events, status, error };
}
