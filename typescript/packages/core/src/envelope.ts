/**
 * The wire protocol envelope. Must match the Python `eventloom.core.envelope.StreamEnvelope`
 * Pydantic model byte-for-byte (as JSON) — see `eventloom-project-plan.md` section 2 for the
 * frozen contract. Do not change field names/semantics here without a matching backend change.
 */

/** How a new envelope's `data` combines with prior envelopes sharing the same `id`. */
export type MergeStrategy = "replace" | "merge" | "append";

/** One JSON object per SSE `data:` line. */
export interface StreamEnvelope<T = unknown> {
  /** Event type, e.g. "chart.data" — routes to a component via the registry. */
  type: string;
  /** Groups events belonging to the same logical "thing" (e.g. all partials for one chart). */
  id: string;
  /** Monotonic sequence number within this `id`, for ordering/dedupe. */
  seq: number;
  /** Event-specific payload. */
  data: T;
  /** How this event combines with prior ones sharing `id`. */
  strategy: MergeStrategy;
  /** True if this is the final event for this `id`. */
  done: boolean;
  /** ISO timestamp, for debugging/latency measurement. */
  ts: string;
}

/** The built-in error event type, mirroring `eventloom.core.envelope.STREAM_ERROR_TYPE`. */
export const STREAM_ERROR_TYPE = "__stream_error__";

/** Payload shape for `STREAM_ERROR_TYPE` envelopes, mirroring `eventloom.core.envelope.StreamError`. */
export interface StreamErrorData {
  message: string;
  code?: string | null;
}

/** Runtime guard: does `value` look like a well-formed `StreamEnvelope`?
 *
 * Used by `StreamConnection` to reject malformed frames (e.g. a proxy
 * injecting an HTML error page into the stream) instead of crashing the
 * caller with a `TypeError` deep inside a merge.
 */
export function isStreamEnvelope(value: unknown): value is StreamEnvelope {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.type === "string" &&
    typeof v.id === "string" &&
    typeof v.seq === "number" &&
    "data" in v &&
    (v.strategy === "replace" || v.strategy === "merge" || v.strategy === "append") &&
    typeof v.done === "boolean" &&
    typeof v.ts === "string"
  );
}
