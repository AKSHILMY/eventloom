import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { StreamEnvelope } from "@akshilmy/eventloom-core";
import { StreamView } from "../src/StreamView";
import { createRegistry } from "../src/createRegistry";
import type { EventComponentProps } from "../src/createRegistry";

function sseBody(frames: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let i = 0;
  return new ReadableStream({
    pull(controller) {
      if (i < frames.length) {
        controller.enqueue(encoder.encode(frames[i]));
        i++;
      } else {
        controller.close();
      }
    },
  });
}

function envelopeFrame(overrides: Partial<StreamEnvelope>): string {
  const full: StreamEnvelope = {
    type: "chart.data",
    id: "id-1",
    seq: 0,
    data: {},
    strategy: "replace",
    done: false,
    ts: "2026-08-18T00:00:00Z",
    ...overrides,
  };
  return `data: ${JSON.stringify(full)}\n\n`;
}

interface ChartData {
  labels: string[];
}

function ChartWidget({ data }: EventComponentProps<ChartData>) {
  return <div data-testid="chart">{data.labels.join(",")}</div>;
}

function Fallback({ }: EventComponentProps<unknown>) {
  return <div data-testid="fallback">unknown event</div>;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StreamView", () => {
  it("renders the registered component for a known event type", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(sseBody([envelopeFrame({ id: "c1", data: { labels: ["Q1", "Q2"] }, done: true })]), {
          status: 200,
        })
      )
    );
    const registry = createRegistry().register("chart.data", { renderer: ChartWidget });

    render(<StreamView endpoint="/stream/dashboard" registry={registry} reconnect={false} />);

    await waitFor(() => expect(screen.getByTestId("chart")).toHaveTextContent("Q1,Q2"));
  });

  it("renders the fallback for an unregistered event type", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(sseBody([envelopeFrame({ type: "mystery.event", id: "m1", data: {} })]), { status: 200 })
      )
    );
    const registry = createRegistry().register("chart.data", { renderer: ChartWidget });

    render(<StreamView endpoint="/stream/dashboard" registry={registry} fallback={Fallback} reconnect={false} />);

    await waitFor(() => expect(screen.getByTestId("fallback")).toBeInTheDocument());
  });

  it("renders the fallback for the built-in __stream_error__ type since apps never register it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          sseBody([
            envelopeFrame({
              type: "__stream_error__",
              id: "__stream_error__",
              data: { message: "boom" },
              done: true,
            }),
          ]),
          { status: 200 }
        )
      )
    );
    const registry = createRegistry().register("chart.data", { renderer: ChartWidget });

    render(<StreamView endpoint="/stream/dashboard" registry={registry} fallback={Fallback} reconnect={false} />);

    await waitFor(() => expect(screen.getByTestId("fallback")).toBeInTheDocument());
  });

  it("renders nothing for an unregistered type when no fallback is given", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(sseBody([envelopeFrame({ type: "mystery.event", id: "m1", data: {} })]), { status: 200 })
      )
    );
    const registry = createRegistry().register("chart.data", { renderer: ChartWidget });

    const { container } = render(<StreamView endpoint="/stream/dashboard" registry={registry} reconnect={false} />);

    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledOnce());
    expect(container.textContent).toBe("");
  });

  it("renders multiple events, each through its own registered component", async () => {
    // "append" strategy accumulates into an array — the id's snapshot.data is
    // every emitted item so far, not just the latest one (plan section 4.2).
    function LogList({ data }: EventComponentProps<Array<{ text: string }>>) {
      return (
        <ul>
          {data.map((line, i) => (
            <li key={i}>{line.text}</li>
          ))}
        </ul>
      );
    }

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          sseBody([
            envelopeFrame({ type: "chart.data", id: "c1", data: { labels: ["Q1"] } }),
            envelopeFrame({ type: "log.line", id: "l1", data: { text: "hello" }, strategy: "append" }),
          ]),
          { status: 200 }
        )
      )
    );
    const registry = createRegistry()
      .register("chart.data", { renderer: ChartWidget })
      .register("log.line", { renderer: LogList });

    render(<StreamView endpoint="/stream/dashboard" registry={registry} reconnect={false} />);

    await waitFor(() => expect(screen.getByTestId("chart")).toBeInTheDocument());
    expect(screen.getByText("hello")).toBeInTheDocument();
  });
});
