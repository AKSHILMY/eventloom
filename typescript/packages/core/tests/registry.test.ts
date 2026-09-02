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

describe("ComponentRegistry.registerModel", () => {
  it("registers the merge event for the prefix", () => {
    const registry = new ComponentRegistry().registerModel("company.profile", {
      renderer: "ProfileCard",
    });
    const config = registry.get("company.profile");
    expect(config?.renderer).toBe("ProfileCard");
    expect(config?.strategy).toBe("merge");
  });

  it("registers append events for each declared list field", () => {
    const registry = new ComponentRegistry().registerModel("company.profile", {
      renderer: "ProfileCard",
      fields: {
        key_products: { renderer: "KeyProductItem" },
      },
    });
    const listConfig = registry.get("company.profile.key_products");
    expect(listConfig?.renderer).toBe("KeyProductItem");
    expect(listConfig?.strategy).toBe("append");
  });

  it("respects explicit strategy overrides on the parent event", () => {
    const registry = new ComponentRegistry().registerModel("log.stream", {
      renderer: "LogView",
      strategy: "replace",
    });
    expect(registry.get("log.stream")?.strategy).toBe("replace");
  });

  it("respects explicit strategy overrides on list fields", () => {
    const registry = new ComponentRegistry().registerModel("example", {
      renderer: "ExampleView",
      fields: {
        items: { renderer: "ItemView", strategy: "replace" },
      },
    });
    expect(registry.get("example.items")?.strategy).toBe("replace");
  });

  it("lists all registered types including list field subtypes", () => {
    const registry = new ComponentRegistry().registerModel("company.profile", {
      renderer: "ProfileCard",
      fields: {
        key_products: { renderer: "KeyProductItem" },
        insights: { renderer: "InsightCard" },
      },
    });
    expect(registry.types().sort()).toEqual([
      "company.profile",
      "company.profile.insights",
      "company.profile.key_products",
    ]);
  });

  it("registerModel is chainable with register()", () => {
    const registry = new ComponentRegistry()
      .registerModel("company.profile", { renderer: "ProfileCard" })
      .register("activity.log", { renderer: "LogLine", strategy: "append" });

    expect(registry.has("company.profile")).toBe(true);
    expect(registry.has("activity.log")).toBe(true);
  });
});
