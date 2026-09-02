/**
 * EvaluationPage — complex-auto-v1 demo.
 *
 * The entire backend is:
 *   registry.register_model("evaluation", V1EvaluationGrid)
 *   await stream_model(emitter, "evaluation", V1EvaluationGrid, client, model, [prompt])
 *
 * register_model auto-derives two event types:
 *   "evaluation"          → merge  (overall_score + description fill in at end)
 *   "evaluation.sections" → append (one complete V1EvalSection per new item)
 *
 * StreamView + a three-entry registry handles everything — no custom hook needed.
 */
import { createRegistry, StreamView } from "@akshilmy/eventloom-react";
import type { EventComponentProps } from "@akshilmy/eventloom-react";
import { ActivityLog, ErrorFallback } from "./components";
import type { LogLine } from "./components";

// --- Types -------------------------------------------------------------------

type SectionType = "basic" | "framework" | "advanced";
type EvalLevel   = "beginner" | "intermediate" | "expert";

interface EvalCriteria {
  name?:     string;
  level?:    EvalLevel;
  improve?:  string;
  you_said?: string;
  stronger?: string;
}

interface EvalSection {
  title?:        string;
  section_type?: SectionType;
  criterias?:    EvalCriteria[];  // included in each section payload
}

/** Scalar fields from the top-level V1EvaluationGrid (arrive via merge at end). */
interface EvalMeta {
  overall_score?: number;
  description?:  string;
}

// --- Design tokens -----------------------------------------------------------

const TYPE_CONFIG: Record<SectionType, { label: string; color: string; border: string }> = {
  basic:     { label: "BASIC",     color: "text-weft",   border: "border-l-weft" },
  framework: { label: "FRAMEWORK", color: "text-thread", border: "border-l-thread" },
  advanced:  { label: "ADVANCED",  color: "text-warp",   border: "border-l-warp" },
};

const LEVEL_CONFIG: Record<EvalLevel, { icon: string; label: string; className: string }> = {
  beginner:     { icon: "✗", label: "Beginner",     className: "text-risk" },
  intermediate: { icon: "—", label: "Intermediate", className: "text-thread" },
  expert:       { icon: "✓", label: "Expert",       className: "text-positive" },
};

// --- Sub-components ----------------------------------------------------------

function LevelBadge({ level }: { level?: string }) {
  const safe: EvalLevel | undefined =
    level === "beginner" || level === "intermediate" || level === "expert" ? level : undefined;
  if (!safe) {
    return (
      <span className="inline-flex shrink-0 items-center gap-1 font-mono text-[11px] text-mist">
        — <span>Intermediate</span>
      </span>
    );
  }
  const { icon, label, className } = LEVEL_CONFIG[safe];
  return (
    <span className={`inline-flex shrink-0 items-center gap-1 font-mono text-[11px] font-semibold ${className}`}>
      {icon} <span>{label}</span>
    </span>
  );
}

function CriteriaRow({ criteria }: { criteria: EvalCriteria }) {
  return (
    <div className="animate-rise border-t border-panel-line pt-3 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <LevelBadge level={criteria.level} />
        {criteria.name && (
          <span className="font-mono text-sm font-semibold text-paper">{criteria.name}</span>
        )}
      </div>
      {criteria.improve && (
        <p className="mt-1 text-xs leading-relaxed text-mist">{criteria.improve}</p>
      )}
      {criteria.you_said && (
        <blockquote className="mt-2 rounded-r border-l-2 border-weft bg-ink px-3 py-2">
          <p className="font-mono text-[10px] font-medium uppercase tracking-wider text-mist">You said</p>
          <p className="mt-0.5 text-xs italic text-paper">"{criteria.you_said}"</p>
        </blockquote>
      )}
      {criteria.stronger && (
        <blockquote className="mt-1.5 rounded-r border-l-2 border-thread bg-ink px-3 py-2">
          <p className="font-mono text-[10px] font-medium uppercase tracking-wider text-mist">Stronger</p>
          <p className="mt-0.5 text-xs text-paper">"{criteria.stronger}"</p>
        </blockquote>
      )}
    </div>
  );
}

function EvalSectionCard({ section }: { section: EvalSection }) {
  const rawType = section.section_type;
  const type: SectionType =
    rawType === "basic" || rawType === "framework" || rawType === "advanced" ? rawType : "basic";
  const config = TYPE_CONFIG[type];
  const criterias = section.criterias ?? [];

  return (
    <div className={`animate-rise rounded-xl border border-panel-line border-l-4 ${config.border} bg-panel p-5`}>
      <div className="mb-4">
        <p className={`font-mono text-[10px] font-semibold uppercase tracking-widest ${config.color}`}>
          {config.label}
        </p>
        <h3 className="mt-0.5 font-mono text-[15px] font-semibold leading-snug text-paper">
          {section.title || <span className="text-mist">…</span>}
        </h3>
      </div>
      {criterias.length > 0 ? (
        <div className="space-y-3">
          {criterias.map((c, i) => <CriteriaRow key={c.name ?? i} criteria={c} />)}
        </div>
      ) : (
        <div className="space-y-2">
          {[160, 200, 140].map((w) => (
            <div key={w} className="h-3 animate-pulse rounded bg-panel-line" style={{ width: w }} />
          ))}
        </div>
      )}
    </div>
  );
}

// --- Renderers (registered in evalRegistry below) ----------------------------

/**
 * Renders the score gauge.
 * Registered for "evaluation" (merge) — receives scalar deltas as the LLM fills
 * in overall_score and description at the very end of the stream.
 */
function ScoreGaugeRenderer({ data }: EventComponentProps<EvalMeta>) {
  const score = data?.overall_score;
  const description = data?.description;

  const R = 52;
  const circumference = 2 * Math.PI * R;
  const filled = score != null ? (score / 100) * circumference : 0;
  const scoreColor =
    score == null ? "var(--color-mist)"
    : score >= 80 ? "var(--color-positive)"
    : score >= 60 ? "var(--color-thread)"
    : "var(--color-risk)";

  return (
    <div
      style={{ gridArea: "score" }}
      className="flex flex-wrap items-center gap-6 rounded-xl border border-panel-line bg-panel p-6"
    >
      <div className="relative shrink-0">
        <svg width="132" height="132" viewBox="0 0 132 132" aria-label={`Score ${score ?? "pending"}`}>
          <circle cx="66" cy="66" r={R} fill="none" stroke="var(--color-panel-line)" strokeWidth="10" />
          <circle
            cx="66" cy="66" r={R}
            fill="none"
            stroke={scoreColor}
            strokeWidth="10"
            strokeDasharray={`${filled} ${circumference}`}
            strokeLinecap="round"
            transform="rotate(-90 66 66)"
            style={{ transition: "stroke-dasharray 0.9s cubic-bezier(0.16,1,0.3,1)" }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          {score != null ? (
            <>
              <span className="font-mono text-3xl font-bold leading-none" style={{ color: scoreColor }}>
                {score}
              </span>
              <span className="mt-0.5 font-mono text-[10px] text-mist">/100</span>
            </>
          ) : (
            <span className="font-mono text-2xl text-mist">…</span>
          )}
        </div>
      </div>
      <div className="min-w-0 flex-1">
        <p className="font-mono text-xs uppercase tracking-wider text-mist">Overall Score</p>
        <div className="mt-1">
          {description ? (
            <p className="text-sm leading-relaxed text-paper">{description}</p>
          ) : (
            <div className="space-y-1.5">
              {[220, 180, 140].map((w) => (
                <div key={w} className="h-3 animate-pulse rounded bg-panel-line" style={{ width: w }} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Renders all evaluation sections.
 * Registered for "evaluation.sections" (append) — receives the accumulated
 * EvalSection[] array; each section is complete with all criteria when it arrives.
 */
function SectionsFeed({ data }: EventComponentProps<EvalSection[]>) {
  const sections = data ?? [];

  if (sections.length === 0) {
    return (
      <div style={{ gridArea: "grid" }} className="eval-sections-grid">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-56 animate-pulse rounded-xl border border-panel-line bg-panel" />
        ))}
      </div>
    );
  }

  return (
    <div style={{ gridArea: "grid" }} className="eval-sections-grid">
      {sections.map((s, i) => (
        <EvalSectionCard key={s.title ?? i} section={s} />
      ))}
    </div>
  );
}

// --- Registry ----------------------------------------------------------------

const evalRegistry = createRegistry()
  // "evaluation" merge — scalar fields: overall_score, description
  .register<"evaluation", EvalMeta>("evaluation", {
    renderer: ScoreGaugeRenderer,
    strategy: "merge",
  })
  // "evaluation.sections" append — one complete V1EvalSection per new item
  .register<"evaluation.sections", EvalSection[]>("evaluation.sections", {
    renderer: SectionsFeed,
    strategy: "append",
  })
  // activity log
  .register<"activity.log", LogLine[]>("activity.log", {
    renderer: ActivityLog,
    strategy: "append",
  });

// --- Page chrome -------------------------------------------------------------

function LoomMark() {
  return (
    <svg width="22" height="22" viewBox="0 0 28 28" fill="none" aria-hidden className="shrink-0">
      <line x1="7"  y1="4" x2="7"  y2="24" stroke="var(--color-warp)"  strokeWidth="2" />
      <line x1="14" y1="4" x2="14" y2="24" stroke="var(--color-warp)"  strokeWidth="2" />
      <line x1="21" y1="4" x2="21" y2="24" stroke="var(--color-warp)"  strokeWidth="2" />
      <line x1="3"  y1="9" x2="25" y2="9"  stroke="var(--color-weft)"  strokeWidth="2" />
      <line x1="3" y1="19" x2="25" y2="19" stroke="var(--color-weft)"  strokeWidth="2" />
      <circle cx="14" cy="14" r="2.5" fill="var(--color-thread)" />
    </svg>
  );
}

// --- Page --------------------------------------------------------------------

export function EvaluationPage() {
  return (
    <div className="min-h-screen bg-ink text-paper">
      {/* ── Header ── */}
      <header className="border-b border-panel-line">
        <div className="mx-auto flex max-w-screen-xl flex-wrap items-center justify-between gap-4 px-6 py-4 sm:px-10">
          <div className="flex items-center gap-3">
            <LoomMark />
            <div>
              <h1 className="font-mono text-base font-semibold leading-none tracking-tight">
                Roleplay Evaluation
              </h1>
              <p className="mt-0.5 font-mono text-[11px] text-mist">
                complex-auto-v1 · one schema · one prompt · port 8005
              </p>
            </div>
          </div>
          <nav className="font-mono text-xs">
            <a href="#/" className="text-mist transition-colors hover:text-paper">← Dashboard</a>
          </nav>
        </div>
      </header>

      {/* ── Body ── */}
      <main className="mx-auto max-w-screen-xl px-6 py-6 sm:px-10">
        <p className="max-w-2xl text-sm leading-relaxed text-mist">
          One{" "}
          <code className="rounded bg-panel px-1 py-0.5 font-mono text-[12px] text-paper">
            register_model()
          </code>{" "}
          call on a nested schema, one{" "}
          <code className="rounded bg-panel px-1 py-0.5 font-mono text-[12px] text-paper">
            stream_model()
          </code>{" "}
          call with a single prompt — eventloom derives the{" "}
          <code className="rounded bg-panel px-1 py-0.5 font-mono text-[12px] text-paper">
            evaluation.sections
          </code>{" "}
          append stream automatically. Sections materialise one by one, each fully formed.
        </p>

        {/*
          StreamView renders in store insertion order:
            ScoreGaugeRenderer (gridArea: "score") — fills in at the end
            SectionsFeed       (gridArea: "grid")  — sections appear one by one
            ActivityLog        (gridArea: "log")   — right column
        */}
        <div className="eval-page-grid mt-6">
          <StreamView
            endpoint="http://localhost:8005/stream/dashboard"
            registry={evalRegistry}
            fallback={ErrorFallback}
          />
        </div>
      </main>
    </div>
  );
}
