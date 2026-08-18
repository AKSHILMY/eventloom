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
