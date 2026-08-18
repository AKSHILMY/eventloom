import { createRegistry, StreamView } from "@akshilmy/eventloom-react";
import { ActivityLog, ErrorFallback, InsightFeed, MetricsChart, ProfileCard } from "./components";
import type { CompanyProfile, Insight, LogLine, MetricsBreakdown } from "./components";

const registry = createRegistry()
  .register<"company.profile", CompanyProfile>("company.profile", { renderer: ProfileCard, strategy: "merge" })
  .register<"company.insight", Insight[]>("company.insight", { renderer: InsightFeed, strategy: "append" })
  .register<"company.metrics", MetricsBreakdown>("company.metrics", { renderer: MetricsChart })
  .register<"activity.log", LogLine[]>("activity.log", { renderer: ActivityLog, strategy: "append" });

// Cross-origin, direct to the backend — not proxied through Vite's dev
// server. See dashboard_app.py's CORSMiddleware comment for why: a
// same-origin dev proxy can forward unrelated cookies other local apps set
// broadly on `localhost`, and large ones can break naive proxies outright.
const BACKEND_URL = "http://localhost:8000";

// Two threads running lengthwise (warp) and crosswise (weft) on a loom, plus
// the single strand (thread) woven through them — the same three colors used
// for the replace/append/merge badges throughout the dashboard below.
function LoomMark() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" fill="none" aria-hidden className="shrink-0">
      <line x1="7" y1="4" x2="7" y2="24" stroke="var(--color-warp)" strokeWidth="2" />
      <line x1="14" y1="4" x2="14" y2="24" stroke="var(--color-warp)" strokeWidth="2" />
      <line x1="21" y1="4" x2="21" y2="24" stroke="var(--color-warp)" strokeWidth="2" />
      <line x1="3" y1="9" x2="25" y2="9" stroke="var(--color-weft)" strokeWidth="2" />
      <line x1="3" y1="19" x2="25" y2="19" stroke="var(--color-weft)" strokeWidth="2" />
      <circle cx="14" cy="14" r="2.5" fill="var(--color-thread)" />
    </svg>
  );
}

export function App() {
  return (
    <div className="min-h-screen bg-ink text-paper">
      <header className="border-b border-panel-line">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-4 px-6 py-5 sm:px-10">
          <div className="flex items-center gap-3">
            <LoomMark />
            <div>
              <h1 className="font-mono text-lg font-semibold leading-none tracking-tight">eventloom</h1>
              <p className="mt-1 text-xs text-mist">dashboard example</p>
            </div>
          </div>
          <ul className="flex flex-wrap gap-x-5 gap-y-1">
            <li className="flex items-center gap-1.5 font-mono text-xs text-mist">
              <span className="h-1.5 w-1.5 rounded-full bg-thread" />
              <span className="text-paper">merge</span>
              <span className="hidden sm:inline">— fields fill in over time</span>
            </li>
            <li className="flex items-center gap-1.5 font-mono text-xs text-mist">
              <span className="h-1.5 w-1.5 rounded-full bg-weft" />
              <span className="text-paper">append</span>
              <span className="hidden sm:inline">— items stack up as they arrive</span>
            </li>
            <li className="flex items-center gap-1.5 font-mono text-xs text-mist">
              <span className="h-1.5 w-1.5 rounded-full bg-warp" />
              <span className="text-paper">replace</span>
              <span className="hidden sm:inline">— one complete result</span>
            </li>
          </ul>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-10 sm:px-10">
        <p className="max-w-2xl text-sm leading-relaxed text-mist">
          Backed by{" "}
          <code className="rounded bg-panel px-1.5 py-0.5 font-mono text-[13px] text-paper">
            python/eventloom/examples/dashboard_app.py
          </code>
          , which fires three concurrent{" "}
          <code className="rounded bg-panel px-1.5 py-0.5 font-mono text-[13px] text-paper">instructor</code>
          -powered LLM calls — a field-by-field partial stream, a multi-object append stream, and a one-shot
          structured extraction, researching the same fictional startup — over a single SSE connection. Run it
          with{" "}
          <code className="rounded bg-panel px-1.5 py-0.5 font-mono text-[13px] text-paper">
            python examples/dashboard_app.py
          </code>{" "}
          (needs an LLM API key — see the file's docstring) before starting this app.
        </p>

        <div className="dashboard-grid mt-8">
          <StreamView endpoint={`${BACKEND_URL}/stream/dashboard`} registry={registry} fallback={ErrorFallback} />
        </div>
      </main>
    </div>
  );
}
