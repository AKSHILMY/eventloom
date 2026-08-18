import type { ComponentType } from "react";
import type { EventComponentProps, TypedComponentRegistry } from "./createRegistry";
import { useEventStream, type UseEventStreamOptions } from "./useEventStream";

export interface StreamViewProps extends UseEventStreamOptions {
  endpoint: string;
  registry: TypedComponentRegistry<Record<string, unknown>>;
  /**
   * Rendered for any event type not present in `registry` — this includes
   * the built-in `__stream_error__` type (see the Python package's error
   * handling contract), since apps don't register it themselves.
   */
  fallback?: ComponentType<EventComponentProps<unknown>> | null;
}

/** The batteries-included way to render a stream: endpoint + registry -> output. */
export function StreamView({ endpoint, registry, fallback = null, ...streamOptions }: StreamViewProps) {
  const { events } = useEventStream(endpoint, { ...streamOptions, registry });

  return (
    <>
      {events.map((event) => {
        const config = registry.get(event.type);
        if (!config) {
          if (!fallback) return null;
          const Fallback = fallback;
          return <Fallback key={event.id} id={event.id} data={event.data} done={event.done} />;
        }
        const Component = config.renderer;
        return <Component key={event.id} id={event.id} data={event.data} done={event.done} />;
      })}
    </>
  );
}
