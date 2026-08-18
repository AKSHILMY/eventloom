import type { StreamEnvelope } from "./envelope";

interface StoredEvent {
  type: string;
  data: unknown;
  done: boolean;
  seq: number;
}

/** A flattened view of one logical event group (`id`), ready to render. */
export interface EventSnapshot {
  id: string;
  type: string;
  data: unknown;
  done: boolean;
}

/**
 * In-memory event store: applies the `replace` / `merge` / `append` logic
 * per `id`, keyed by the strategy declared on each incoming envelope (which
 * defaults to whatever the backend registered, see `RendererConfig.strategy`
 * for how an adapter can override it per registration).
 */
export class EventStore {
  private byId = new Map<string, StoredEvent>();

  /** Apply one envelope, combining it with any prior state for the same `id`. */
  apply(envelope: StreamEnvelope): void {
    const existing = this.byId.get(envelope.id);

    // Defensive ordering/dedupe guard. SSE guarantees in-order delivery per
    // connection in practice, but a reconnect can replay an already-applied
    // event — don't let a stale `seq` clobber a newer one (plan section 2).
    if (existing && envelope.seq <= existing.seq) return;

    let next: unknown;
    switch (envelope.strategy) {
      case "replace":
        next = envelope.data;
        break;
      case "merge":
        next = { ...((existing?.data as Record<string, unknown>) ?? {}), ...(envelope.data as Record<string, unknown>) };
        break;
      case "append":
        next = [...((existing?.data as unknown[]) ?? []), envelope.data];
        break;
    }

    this.byId.set(envelope.id, { type: envelope.type, data: next, done: envelope.done, seq: envelope.seq });
  }

  /** The current combined state for one `id`, if any events have arrived for it. */
  get(id: string): EventSnapshot | undefined {
    const stored = this.byId.get(id);
    if (!stored) return undefined;
    return { id, type: stored.type, data: stored.data, done: stored.done };
  }

  /** Every group's current state, in insertion order of first-seen `id`. */
  snapshot(): EventSnapshot[] {
    return [...this.byId.entries()].map(([id, v]) => ({ id, type: v.type, data: v.data, done: v.done }));
  }

  clear(): void {
    this.byId.clear();
  }
}
