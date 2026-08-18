/**
 * Type-level verification of the section 5.2 claim: "registering the wrong
 * component for an event type is a compile error, not a runtime one."
 *
 * Not a `*.test.ts` file on purpose — vitest never executes this, it exists
 * purely so `npm run typecheck` (`tsc --noEmit`, which includes `tests/` per
 * tsconfig.json) fails if this inference/checking ever regresses.
 *
 * Two ways this holds, without requiring the (deferred, v2) codegen bridge
 * from plan section 5.3:
 *  1. Auto-inference: registering a component with a concrete `data` prop
 *     type just works — T is inferred from the renderer you pass.
 *  2. Explicit pinning: annotate `.register<K, T>()` with the payload type
 *     you maintain by hand (or, later, generate from Pydantic) to catch a
 *     genuinely wrong renderer for that type at the call site.
 */
import type { FC } from "react";
import type { EventComponentProps } from "../src/createRegistry";
import { createRegistry } from "../src/createRegistry";

interface ChartData {
  labels: string[];
  values: number[];
}

const GoodChartWidget: FC<EventComponentProps<ChartData>> = () => null;
const BadChartWidget: FC<EventComponentProps<{ onlyThisField: string }>> = () => null;

// (1) Auto-inference: compiles, T inferred as ChartData from GoodChartWidget.
createRegistry().register("chart.data", { renderer: GoodChartWidget });

// (2) Explicit pinning catches a mismatched renderer for a known payload type.
createRegistry().register<"chart.data", ChartData>("chart.data", { renderer: GoodChartWidget }); // ok

// @ts-expect-error - BadChartWidget's `data` prop doesn't satisfy ChartData.
createRegistry().register<"chart.data", ChartData>("chart.data", { renderer: BadChartWidget });
