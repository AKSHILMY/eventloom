import { describe, expect, it } from "vitest";
import { ComponentRegistry } from "../src/registry";

describe("ComponentRegistry", () => {
  it("registers and retrieves renderer config by type", () => {
    const registry = new ComponentRegistry().register("chart.data", { renderer: "ChartWidget" });

    expect(registry.get("chart.data")).toEqual({ renderer: "ChartWidget" });
    expect(registry.get("missing")).toBeUndefined();
  });

  it("has() reflects registration state", () => {
    const registry = new ComponentRegistry().register("chart.data", { renderer: "x" });
    expect(registry.has("chart.data")).toBe(true);
    expect(registry.has("nope")).toBe(false);
  });

  it("types() lists every registered type", () => {
    const registry = new ComponentRegistry()
      .register("chart.data", { renderer: "x" })
      .register("log.line", { renderer: "y", strategy: "append" });

    expect(registry.types().sort()).toEqual(["chart.data", "log.line"]);
  });

  it("carries a per-registration strategy override", () => {
    const registry = new ComponentRegistry().register("log.line", { renderer: "y", strategy: "append" });
    expect(registry.get("log.line")?.strategy).toBe("append");
  });

  it("register() returns a registry (chainable) rather than mutating in place awkwardly", () => {
    const empty = new ComponentRegistry();
    const withOne = empty.register("chart.data", { renderer: "x" });
    // Same underlying instance (documented behavior: mutates and returns `this`
    // with a widened type), but chaining reads naturally either way.
    expect(withOne).toBe(empty);
    expect(withOne.has("chart.data")).toBe(true);
  });
});
