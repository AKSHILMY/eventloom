import type { ReactNode } from "react";
import type { EventComponentProps, StreamErrorData } from "@akshilmy/eventloom-react";

// Mirrors python/eventloom/examples/dashboard_app.py's Pydantic models — four
// event types, three merge strategies, all researching the same fictional
// startup concurrently over one SSE connection.

// --- Shared chrome ----------------------------------------------------------

type Strategy = "merge" | "append" | "replace";

// One color per strategy, reused everywhere (panel border, badge, dot) so the
// mapping is learnable at a glance — see App.tsx's legend for the names.
const STRATEGY: Record<Strategy, { label: string; dot: string; border: string; badge: string }> = {
  merge: { label: "merge", dot: "bg-thread", border: "border-thread/50", badge: "bg-thread/10 text-thread" },
  append: { label: "append", dot: "bg-weft", border: "border-weft/50", badge: "bg-weft/10 text-weft" },
  replace: { label: "replace", dot: "bg-warp", border: "border-warp/50", badge: "bg-warp/10 text-warp" },
};

function StrategyBadge({ strategy }: { strategy: Strategy }) {
  const s = STRATEGY[strategy];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[11px] font-medium ${s.badge}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}

// `area` places this panel in the named-area grid defined in index.css, so
// layout stays fixed no matter which of the three concurrent LLM calls
// happens to produce its first event first.
function Panel({
  area,
  strategy,
  title,
  children,
}: {
  area: string;
  strategy: Strategy;
  title: string;
  children: ReactNode;
}) {
  return (
    <section
      style={{ gridArea: area }}
      className={`rounded-xl border border-panel-line ${STRATEGY[strategy].border} border-l-4 bg-panel p-5`}
    >
      <header className="mb-4 flex items-center justify-between gap-3">
        <h2 className="font-mono text-sm font-semibold tracking-wide text-paper">{title}</h2>
        <StrategyBadge strategy={strategy} />
      </header>
      {children}
    </section>
  );
}

// A field that isn't in yet renders as a pulsing placeholder; once it
// arrives, `key`ing on its value forces a fresh DOM node so `.animate-rise`
// plays exactly once, right when that piece of the schema shows up.
function FieldValue({ value, placeholder = "w-24" }: { value?: string | number; placeholder?: string }) {
  if (value === undefined || value === null || value === "") {
    return <span className={`inline-block h-[1em] ${placeholder} animate-pulse rounded bg-panel-line align-middle`} />;
  }
  return (
    <span key={String(value)} className="animate-rise inline-block">
      {value}
    </span>
  );
}

// --- company.profile (merge) -------------------------------------------------

export interface CompanyProfile {
  name?: string;
  industry?: string;
  founded_year?: number;
  headquarters?: string;
  description?: string;
  key_products?: string[];
}

export function ProfileCard({ data, done }: EventComponentProps<CompanyProfile>) {
  return (
    <Panel area="profile" strategy="merge" title="Company profile">
      <p className="text-lg font-semibold text-paper">
        <FieldValue value={data.name} placeholder="w-40" />
      </p>
      <p className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm text-mist">
        <FieldValue value={data.industry} placeholder="w-20" />
        <span aria-hidden>·</span>
        <FieldValue value={data.founded_year ? `founded ${data.founded_year}` : undefined} placeholder="w-24" />
        <span aria-hidden>·</span>
        <FieldValue value={data.headquarters} placeholder="w-28" />
      </p>
      <p className="mt-3 text-sm leading-relaxed text-paper/90">
        <FieldValue value={data.description} placeholder="w-full" />
      </p>
      <div className="mt-4 flex flex-wrap gap-1.5">
        {data.key_products?.length
          ? data.key_products.map((product) => (
              <span
                key={product}
                className="animate-rise rounded-full border border-panel-line bg-ink px-2.5 py-1 font-mono text-[11px] text-mist"
              >
                {product}
              </span>
            ))
          : Array.from({ length: 3 }, (_, i) => (
              <span key={i} className="h-6 w-16 animate-pulse rounded-full bg-panel-line" />
            ))}
      </div>
      {!done && <p className="mt-4 font-mono text-[11px] text-thread/80">streaming…</p>}
    </Panel>
  );
}

// --- company.insight (append) ------------------------------------------------

export interface Insight {
  title: string;
  detail: string;
  signal: string;
}

const SIGNAL_STYLE: Record<string, string> = {
  positive: "border-positive/30 bg-positive/10 text-positive",
  risk: "border-risk/30 bg-risk/10 text-risk",
};
const NEUTRAL_SIGNAL_STYLE = "border-panel-line bg-ink text-mist";

export function InsightFeed({ data }: EventComponentProps<Insight[]>) {
  return (
    <Panel area="insights" strategy="append" title="Analyst insights">
      {data.length === 0 ? (
        <p className="font-mono text-[11px] text-mist">
          <span className="animate-pulse">waiting for insights…</span>
        </p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {data.map((insight, i) => (
            <li key={i} className="animate-rise rounded-lg border border-panel-line bg-ink p-3.5">
              <span
                className={`inline-block rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide ${
                  SIGNAL_STYLE[insight.signal] ?? NEUTRAL_SIGNAL_STYLE
                }`}
              >
                {insight.signal}
              </span>
              <h3 className="mt-2 text-sm font-semibold text-paper">{insight.title}</h3>
              <p className="mt-1 text-sm leading-relaxed text-mist">{insight.detail}</p>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

// --- company.metrics (replace) -----------------------------------------------

export interface MetricsBreakdown {
  metric: string;
  labels: string[];
  values: number[];
}

export function MetricsChart({ data, done }: EventComponentProps<MetricsBreakdown>) {
  const max = Math.max(1, ...data.values);
  return (
    <Panel area="metrics" strategy="replace" title="Metrics">
      {data.metric && <p className="-mt-2 mb-4 text-sm text-mist">{data.metric}</p>}
      <div className="flex h-36 items-end gap-3">
        {data.labels.map((label, i) => (
          <div key={label} className="flex flex-1 flex-col items-center gap-2">
            <span className="font-mono text-[11px] text-paper/80">{data.values[i]}</span>
            <div
              className="bar-grow w-full rounded-t bg-warp/80"
              style={{ height: `${((data.values[i] ?? 0) / max) * 96}px` }}
            />
            <span className="text-center font-mono text-[10px] leading-tight text-mist">{label}</span>
          </div>
        ))}
      </div>
      {!done && <p className="mt-3 font-mono text-[11px] text-warp/80">loading…</p>}
    </Panel>
  );
}

// --- activity.log (append) ---------------------------------------------------

export interface LogLine {
  text: string;
}

// Styled as a terminal rather than a fourth card: it's literally raw process
// output from the three concurrent tasks above, so it reads better as a
// console than as another data panel.
export function ActivityLog({ data }: EventComponentProps<LogLine[]>) {
  return (
    <section style={{ gridArea: "log" }} className="overflow-hidden rounded-xl border border-panel-line">
      <header className="flex items-center justify-between gap-3 border-b border-panel-line bg-panel px-5 py-3">
        <h2 className="font-mono text-sm font-semibold tracking-wide text-paper">Activity log</h2>
        <StrategyBadge strategy="append" />
      </header>
      <div className="max-h-64 overflow-y-auto bg-ink p-5 font-mono text-[12.5px] leading-relaxed">
        {data.length === 0 && <p className="animate-pulse text-mist">waiting for events…</p>}
        {data.map((line, i) => (
          <p key={i} className="animate-rise text-mist">
            <span className="mr-1.5 text-weft">❯</span>
            {line.text}
          </p>
        ))}
      </div>
    </section>
  );
}

// --- __stream_error__ ---------------------------------------------------------

export function ErrorFallback({ data }: EventComponentProps<unknown>) {
  const error = data as StreamErrorData;
  return (
    <section style={{ gridColumn: "1 / -1" }} className="rounded-xl border border-risk/40 bg-risk/10 p-5">
      <h2 className="font-mono text-sm font-semibold tracking-wide text-risk">Stream error</h2>
      <p className="mt-2 text-sm text-paper">
        {error.message} {error.code && <span className="text-mist">({error.code})</span>}
      </p>
    </section>
  );
}
