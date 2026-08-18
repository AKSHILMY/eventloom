import { describe, expect, it } from "vitest";
import { isStreamEnvelope } from "../src/envelope";

describe("isStreamEnvelope", () => {
  it("accepts a well-formed envelope", () => {
    expect(
      isStreamEnvelope({
        type: "chart.data",
        id: "chart-1",
        seq: 0,
        data: { labels: [] },
        strategy: "replace",
        done: true,
        ts: "2026-08-18T00:00:00Z",
      })
    ).toBe(true);
  });

  it.each([
    [null],
    [undefined],
    ["a string"],
    [42],
    [{}],
    [{ type: "x" }], // missing everything else
    [{ type: "x", id: "1", seq: "not-a-number", data: {}, strategy: "replace", done: true, ts: "t" }],
    [{ type: "x", id: "1", seq: 0, data: {}, strategy: "invalid-strategy", done: true, ts: "t" }],
    [{ type: "x", id: "1", seq: 0, data: {}, strategy: "replace", done: "not-a-bool", ts: "t" }],
  ])("rejects malformed value %#", (value) => {
    expect(isStreamEnvelope(value)).toBe(false);
  });
});
