import type { EventComponentProps, StreamErrorData } from "@akshilmy/eventloom-react";

// Mirrors python/eventloom/examples/dashboard_app.py's Pydantic models.

export interface ChartData {
  labels: string[];
  values: number[];
}

export function ChartWidget({ data, done }: EventComponentProps<ChartData>) {
  const max = Math.max(1, ...data.values);
  return (
    <section>
      <h2>Quarterly totals {done ? "" : "(loading…)"}</h2>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", height: 120 }}>
        {data.labels.map((label, i) => (
          <div key={label} style={{ textAlign: "center" }}>
            <div
              style={{
                height: `${((data.values[i] ?? 0) / max) * 100}px`,
                width: 40,
                background: "#4f46e5",
              }}
            />
            <div>{label}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

export interface UserProfile {
  name?: string;
  bio?: string;
}

export function UserCard({ data, done }: EventComponentProps<UserProfile>) {
  return (
    <section>
      <h2>Profile {done ? "" : "(loading…)"}</h2>
      <strong>{data.name ?? "…"}</strong>
      <p>{data.bio ?? ""}</p>
    </section>
  );
}

export interface LogLine {
  text: string;
}

// "append" strategy: the store gives us every line emitted so far, in order —
// see @akshilmy/eventloom-core's README for why this is an array, not one item.
export function LogViewer({ data }: EventComponentProps<LogLine[]>) {
  return (
    <section>
      <h2>Activity log</h2>
      <pre>{data.map((line) => line.text).join("\n")}</pre>
    </section>
  );
}

export function ErrorFallback({ data }: EventComponentProps<unknown>) {
  const error = data as StreamErrorData;
  return (
    <section style={{ color: "crimson" }}>
      <h2>Stream error</h2>
      <p>
        {error.message} {error.code ? `(${error.code})` : ""}
      </p>
    </section>
  );
}
