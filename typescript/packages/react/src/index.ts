export { createRegistry, TypedComponentRegistry } from "./createRegistry";
export type { EventComponentProps, ReactRendererConfig } from "./createRegistry";

export { useEventStream } from "./useEventStream";
export type { StreamStatus, UseEventStreamOptions, UseEventStreamResult } from "./useEventStream";

export { StreamView } from "./StreamView";
export type { StreamViewProps } from "./StreamView";

// Re-exported for convenience so consumers of `@akshilmy/eventloom-react` don't
// also need a direct dependency on `@akshilmy/eventloom-core` for common types.
export { STREAM_ERROR_TYPE } from "@akshilmy/eventloom-core";
export type { EventSnapshot, MergeStrategy, StreamEnvelope, StreamErrorData } from "@akshilmy/eventloom-core";
