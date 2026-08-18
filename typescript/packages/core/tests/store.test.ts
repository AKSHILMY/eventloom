import { describe, expect, it } from "vitest";
import { EventStore } from "../src/store";
import type { StreamEnvelope } from "../src/envelope";

function envelope(overrides: Partial<StreamEnvelope>): StreamEnvelope {
  return {
    type: "chart.data",
    id: "id-1",
    seq: 0,
    data: {},
    strategy: "replace",
    done: false,
    ts: "2026-08-18T00:00:00Z",
    ...overrides,
  };
}

describe("EventStore", () => {
  it("replace strategy fully replaces prior data", () => {
    const store = new EventStore();
    store.apply(envelope({ id: "c1", seq: 0, data: { labels: ["Q1"] }, strategy: "replace" }));
    store.apply(envelope({ id: "c1", seq: 1, data: { labels: ["Q1", "Q2"] }, strategy: "replace" }));

    expect(store.get("c1")?.data).toEqual({ labels: ["Q1", "Q2"] });
  });

  it("merge strategy shallow-merges new fields into existing object", () => {
    const store = new EventStore();
    store.apply(envelope({ id: "p1", seq: 0, data: { name: "Ada" }, strategy: "merge" }));
    store.apply(envelope({ id: "p1", seq: 1, data: { bio: "Mathematician" }, strategy: "merge" }));

    expect(store.get("p1")?.data).toEqual({ name: "Ada", bio: "Mathematician" });
  });

  it("append strategy pushes into an array", () => {
    const store = new EventStore();
    store.apply(envelope({ id: "log-1", seq: 0, data: { text: "a" }, strategy: "append" }));
    store.apply(envelope({ id: "log-1", seq: 1, data: { text: "b" }, strategy: "append" }));
    store.apply(envelope({ id: "log-1", seq: 2, data: { text: "c" }, strategy: "append" }));

    expect(store.get("log-1")?.data).toEqual([{ text: "a" }, { text: "b" }, { text: "c" }]);
  });

  it("tracks done flag from the latest applied envelope", () => {
    const store = new EventStore();
    store.apply(envelope({ id: "c1", seq: 0, done: false }));
    expect(store.get("c1")?.done).toBe(false);
    store.apply(envelope({ id: "c1", seq: 1, done: true }));
    expect(store.get("c1")?.done).toBe(true);
  });

  it("ignores a stale/duplicate envelope with seq <= the last applied seq for that id", () => {
    const store = new EventStore();
    store.apply(envelope({ id: "log-1", seq: 0, data: { text: "a" }, strategy: "append" }));
    store.apply(envelope({ id: "log-1", seq: 1, data: { text: "b" }, strategy: "append" }));
    // A reconnect replays seq 1 again — must not be double-appended.
    store.apply(envelope({ id: "log-1", seq: 1, data: { text: "b" }, strategy: "append" }));
    store.apply(envelope({ id: "log-1", seq: 0, data: { text: "a" }, strategy: "append" }));

    expect(store.get("log-1")?.data).toEqual([{ text: "a" }, { text: "b" }]);
  });

  it("keeps independent state per id", () => {
    const store = new EventStore();
    store.apply(envelope({ id: "a", type: "chart.data", data: { v: 1 } }));
    store.apply(envelope({ id: "b", type: "log.line", data: { v: 2 }, strategy: "append" }));

    const snap = store.snapshot();
    expect(snap).toHaveLength(2);
    expect(snap.find((e) => e.id === "a")?.type).toBe("chart.data");
    expect(snap.find((e) => e.id === "b")?.type).toBe("log.line");
  });

  it("clear() empties the store", () => {
    const store = new EventStore();
    store.apply(envelope({ id: "a" }));
    store.clear();
    expect(store.snapshot()).toEqual([]);
  });
});
