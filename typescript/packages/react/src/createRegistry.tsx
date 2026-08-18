import { ComponentRegistry } from "@akshilmy/eventloom-core";
import type { MergeStrategy } from "@akshilmy/eventloom-core";
import type { ComponentType } from "react";

/** Props every registered renderer receives. */
export interface EventComponentProps<T> {
  data: T;
  done: boolean;
  id: string;
}

export interface ReactRendererConfig<T> {
  /**
   * A component typed to accept `data: T`. Because `T` is inferable from
   * this field's concrete prop type (unlike `core.ComponentRegistry`, which
   * deliberately treats `renderer` as opaque — see its docstring), registering
   * a component whose `data` prop doesn't match the type you pass is a
   * **compile error**, not a runtime one (plan section 5.2).
   */
  renderer: ComponentType<EventComponentProps<T>>;
  /** Overrides the backend's declared strategy for this type, if set. */
  strategy?: MergeStrategy;
}

/**
 * A `ComponentRegistry` with a React-aware, type-accumulating `register()`.
 * `TypeMap` grows as `Record<type, T>` with every call, so
 * `registry.register("chart.data", { renderer: ChartWidget })` fails to
 * compile if `ChartWidget`'s `data` prop doesn't match `ChartData`.
 */
export class TypedComponentRegistry<TypeMap extends Record<string, unknown> = Record<string, never>> {
  constructor(private readonly inner: ComponentRegistry<TypeMap> = new ComponentRegistry()) {}

  register<K extends string, T>(
    type: K,
    config: ReactRendererConfig<T>
  ): TypedComponentRegistry<TypeMap & Record<K, T>> {
    this.inner.register(type, config);
    return this as unknown as TypedComponentRegistry<TypeMap & Record<K, T>>;
  }

  get(type: string): ReactRendererConfig<unknown> | undefined {
    return this.inner.get(type) as ReactRendererConfig<unknown> | undefined;
  }

  has(type: string): boolean {
    return this.inner.has(type);
  }

  types(): string[] {
    return this.inner.types();
  }
}

/** Start a new, empty typed registry: `createRegistry().register(...).register(...)`. */
export function createRegistry(): TypedComponentRegistry {
  return new TypedComponentRegistry();
}
