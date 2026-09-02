import { useEffect, useState } from "react";
import { createRegistry, StreamView } from "@akshilmy/eventloom-react";
import { ActivityLog, CompetitorCard, ErrorFallback, InsightFeed, MetricsChart, ProfileCard } from "./components";
import type { CompanyProfile, Insight, LogLine, MetricsBreakdown } from "./components";
import { EvaluationPage } from "./EvaluationPage";

// One registry shared across all four StreamView instances.  The registry is
// a renderer-lookup table, not a state store — each StreamView accumulates
// its own event state independently via the useEventStream hook inside it.
const registry = createRegistry()
  .register<"company.profile", CompanyProfile>("company.profile", { renderer: ProfileCard, strategy: "merge" })
  .register<"company.insight", Insight[]>("company.insight", { renderer: InsightFeed, strategy: "append" })
  .register<"company.metrics", MetricsBreakdown>("company.metrics", { renderer: MetricsChart })
  .register<"activity.log", LogLine[]>("activity.log", { renderer: ActivityLog, strategy: "append" })
  // Emitted only by dashboard_app_pydantic_v1.py / dashboard_unified manual-v1.
  // Harmless no-op against modes that never emit it.
  .register<"company.competitor", CompanyProfile>("company.competitor", { renderer: CompetitorCard, strategy: "merge" })
  // Emitted by auto modes (auto-v1, auto-v2) when register_model() detects a
  // list[SubModel] field.  Registered here with a null renderer so auto-mode
  // panels silently ignore these sub-events rather than routing them to
  // ErrorFallback.  The parent ProfileCard already shows key_products from the
  // merge stream (as list[str] in the unified example), so no separate rendering
  // is needed.
  .register<"company.profile.key_products", unknown>(
    "company.profile.key_products",
    { renderer: () => null, strategy: "append" },
  );

// Four backend instances, each running dashboard_unified.py on its own port.
// The unified frontend connects to all four simultaneously to prove that the
// SSE wire protocol is identical regardless of which flow produced the events.
const MODES = [
  {
    key: "manual-v1",
    port: 8001,
    label: "Manual · Pydantic v1",
    sub:   "OpenAIStreamClient + sent dict",
  },
  {
    key: "manual-v2",
    port: 8002,
    label: "Manual · Pydantic v2",
    sub:   "instructor + sent dict",
  },
  {
    key: "auto-v1",
    port: 8003,
    label: "Auto · Pydantic v1",
    sub:   "register_model + stream_model (v1)",
  },
  {
    key: "auto-v2",
    port: 8004,
    label: "Auto · Pydantic v2",
    sub:   "register_model + stream_model (v2)",
  },
] as const;

// --- Hash-based routing ------------------------------------------------------

function usePage() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const handler = () => setHash(window.location.hash);
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);
  return hash;
}

// --- Shared chrome -----------------------------------------------------------

function LoomMark() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" fill="none" aria-hidden className="shrink-0">
      <line x1="7"  y1="4" x2="7"  y2="24" stroke="var(--color-warp)"   strokeWidth="2" />
      <line x1="14" y1="4" x2="14" y2="24" stroke="var(--color-warp)"   strokeWidth="2" />
      <line x1="21" y1="4" x2="21" y2="24" stroke="var(--color-warp)"   strokeWidth="2" />
      <line x1="3"  y1="9" x2="25" y2="9"  stroke="var(--color-weft)"   strokeWidth="2" />
      <line x1="3" y1="19" x2="25" y2="19" stroke="var(--color-weft)"   strokeWidth="2" />
      <circle cx="14" cy="14" r="2.5"       fill="var(--color-thread)"              />
    </svg>
  );
}

// --- Pages -------------------------------------------------------------------

function DashboardPage() {
  return (
    <div className="min-h-screen bg-ink text-paper">
      {/* ── Header ── */}
      <header className="border-b border-panel-line">
        <div className="mx-auto flex max-w-screen-2xl flex-wrap items-center justify-between gap-4 px-6 py-5 sm:px-10">
          <div className="flex items-center gap-3">
            <LoomMark />
            <div>
              <h1 className="font-mono text-lg font-semibold leading-none tracking-tight">eventloom</h1>
              <p className="mt-1 text-xs text-mist">four flows · one wire protocol</p>
            </div>
          </div>
          <div className="flex items-center gap-6">
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
            <nav className="hidden sm:flex gap-3 font-mono text-xs border-l border-panel-line pl-6">
              <a href="#/complex-example-auto-v1" className="text-mist hover:text-paper transition-colors">
                Evaluation →
              </a>
            </nav>
          </div>
        </div>
      </header>

      {/* ── Body ── */}
      <main className="mx-auto max-w-screen-2xl px-6 py-8 sm:px-10">
        <p className="max-w-3xl text-sm leading-relaxed text-mist">
          All four panels stream the same fictional startup from four independent backends
          running{" "}
          <code className="rounded bg-panel px-1.5 py-0.5 font-mono text-[13px] text-paper">
            dashboard_unified.py
          </code>{" "}
          on ports 8001–8004. The wire protocol — the{" "}
          <code className="rounded bg-panel px-1.5 py-0.5 font-mono text-[13px] text-paper">
            StreamEnvelope
          </code>{" "}
          JSON — is identical regardless of which Pydantic version or which flow produced it.
          This page needs zero per-panel customisation; one shared registry drives all four{" "}
          <code className="rounded bg-panel px-1.5 py-0.5 font-mono text-[13px] text-paper">
            {"<StreamView>"}
          </code>{" "}
          instances.
        </p>
        <p className="mt-2 max-w-3xl text-xs text-mist">
          Start each backend in a separate terminal:
          {" "}
          <code className="rounded bg-panel px-1.5 py-0.5 font-mono text-[12px] text-paper">
            python examples/dashboard_unified.py --mode manual-v1 --port 8001
          </code>
          {" "}…and so on for ports 8002–8004.
        </p>

        {/* ── 2×2 mode grid ── */}
        <div className="modes-grid mt-8">
          {MODES.map((mode) => (
            <section key={mode.key} className="mode-panel">
              {/* Mode label */}
              <div className="mode-header">
                <h2 className="font-mono text-sm font-semibold text-paper">{mode.label}</h2>
                <span className="font-mono text-xs text-mist">{mode.sub}</span>
                <span className="ml-auto font-mono text-xs text-mist">:{mode.port}</span>
              </div>

              {/* Mini dashboard — identical to the standalone examples */}
              <div className="dashboard-grid mt-4">
                <StreamView
                  endpoint={`http://localhost:${mode.port}/stream/dashboard`}
                  registry={registry}
                  fallback={ErrorFallback}
                />
              </div>
            </section>
          ))}
        </div>
      </main>
    </div>
  );
}

// --- Root --------------------------------------------------------------------

export function App() {
  const page = usePage();
  if (page === "#/complex-example-auto-v1") return <EvaluationPage />;
  return <DashboardPage />;
}
