import type { MergeStrategy } from "./envelope";

/**
 * Opaque per-type configuration. `core` doesn't know what a "renderer" is —
 * adapters decide (a React component, a Vue component, a render function for
 * vanilla JS, ...). Core just stores it and accumulates the type-level
 * mapping of event type name -> payload type, which adapters build on to
 * give you compile-time-checked registration (see `@akshilmy/eventloom-react`'s
 * `createRegistry()`, which narrows `renderer` to `ComponentType<{ data: T }>`
 * so passing a component with the wrong prop type is a compile error).
 */
export interface RendererConfig<T = unknown> {
  renderer: unknown;
  /** Overrides the backend's declared strategy for this type, if set. */
  strategy?: MergeStrategy;
}

/**
 * Per-field configuration for list fields registered via `registerModel`.
 * Mirrors the backend's auto-derived `"{prefix}.{field}"` append event type.
 */
export interface ModelFieldConfig<T = unknown> {
  /** The renderer to use for each item in this list field's append stream. */
  renderer: unknown;
  /** Strategy override (defaults to "append" which matches the backend). */
  strategy?: MergeStrategy;
}

/**
 * Configuration for `registerModel` — registers a merge event type for the
 * parent model's scalar fields plus an append event type per list field,
 * mirroring what `EventTypeRegistry.register_model()` auto-derives on the
 * Python backend.
 */
export interface ModelRegistrationConfig<
  ScalarPayload = unknown,
  Fields extends Record<string, unknown> = Record<string, unknown>,
> {
  /** Renderer for the parent merge event (scalar / nested-model fields). */
  renderer: unknown;
  /** Strategy override for the merge event (default: "merge"). */
  strategy?: MergeStrategy;
  /**
   * Per-field renderers for list fields that have their own append stream.
   * Keys must match the field names used when calling `register_model` on
   * the Python backend (e.g. `key_products` → event type `"{prefix}.key_products"`).
   */
  fields?: {
    [K in keyof Fields]?: ModelFieldConfig<Fields[K]>;
  };
}

/**
 * Maps event type name -> renderer config. `TypeMap` accumulates at the type
 * level as you call `.register()`, so `registry.get(type)` narrows and
 * mismatched types are caught by adapters that build stricter `register()`
 * signatures on top of this class (see plan section 5.2).
 */
export class ComponentRegistry<TypeMap extends Record<string, unknown> = Record<string, never>> {
  private entries = new Map<string, RendererConfig<unknown>>();

  register<K extends string, T>(
    type: K,
    config: RendererConfig<T>
  ): ComponentRegistry<TypeMap & Record<K, T>> {
    this.entries.set(type, config as RendererConfig<unknown>);
    return this as unknown as ComponentRegistry<TypeMap & Record<K, T>>;
  }

  /**
   * Convenience helper that mirrors `EventTypeRegistry.register_model()` on
   * the Python backend.  Registers:
   *
   * - `prefix` with `strategy: "merge"` for the parent model's scalar fields.
   * - `"{prefix}.{field}"` with `strategy: "append"` for each list field in
   *   `config.fields`.
   *
   * Example (matching the Python `registry.register_model("company.profile", CompanyProfile)`):
   * ```ts
   * registry.registerModel("company.profile", {
   *   renderer: ProfileCard,
   *   fields: {
   *     key_products: { renderer: KeyProductItem },
   *   },
   * });
   * // Equivalent to:
   * // registry.register("company.profile", { renderer: ProfileCard, strategy: "merge" })
   * // registry.register("company.profile.key_products", { renderer: KeyProductItem, strategy: "append" })
   * ```
   */
  registerModel<K extends string, ScalarPayload, Fields extends Record<string, unknown>>(
    prefix: K,
    config: ModelRegistrationConfig<ScalarPayload, Fields>
  ): ComponentRegistry<TypeMap & Record<K, ScalarPayload>> {
    // Register the parent merge event for scalar fields.
    this.entries.set(prefix, {
      renderer: config.renderer,
      strategy: config.strategy ?? "merge",
    });

    // Register append events for each declared list field.
    if (config.fields) {
      for (const [fieldName, fieldConfig] of Object.entries(config.fields)) {
        if (fieldConfig) {
          this.entries.set(`${prefix}.${fieldName}`, {
            renderer: (fieldConfig as ModelFieldConfig).renderer,
            strategy: (fieldConfig as ModelFieldConfig).strategy ?? "append",
          });
        }
      }
    }

    return this as unknown as ComponentRegistry<TypeMap & Record<K, ScalarPayload>>;
  }

  get(type: string): RendererConfig<unknown> | undefined {
    return this.entries.get(type);
  }

  has(type: string): boolean {
    return this.entries.has(type);
  }

  types(): string[] {
    return [...this.entries.keys()];
  }
}
