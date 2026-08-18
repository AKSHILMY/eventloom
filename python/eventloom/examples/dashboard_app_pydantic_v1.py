"""Runnable example: the same fictional-startup research dashboard as
`dashboard_app.py`, rebuilt on **Pydantic v1** models and
`eventloom.contrib.pydantic_v1` (direct OpenAI tool-calling) instead of
Pydantic v2 + `instructor` (which doesn't support Pydantic v1 schemas).

    pip install "eventloom[examples-pydantic-v1]"
    export OPENAI_API_KEY=sk-...
    python examples/dashboard_app_pydantic_v1.py
    curl -N http://localhost:8000/stream/dashboard

Run this *instead of* `dashboard_app.py` (same port, same route) and point
the unmodified `typescript/examples/react-dashboard` frontend at it: the
wire protocol (`StreamEnvelope` JSON) never changes regardless of which
Pydantic version produced the payload — that's what `eventloom.core._compat`
is for — so the first four event types below render identically either way.
That equivalence is the actual point of this example, not the dashboard
scenario itself.

Five event types, five `eventloom.contrib.pydantic_v1` call shapes:

- `company.profile` (`merge`): `stream_client.stream()` yields an
  ever-more-complete `CompanyProfile` on every chunk. Same diff-against-`sent`
  pattern as `dashboard_app.py`'s `_stream_profile` — each `emitter.emit()`
  call only carries fields new since the last chunk.
- `company.insight` (`append`): `stream_new_list_items()` over a
  `.stream()` of an `InsightsBatch` wrapper — the
  `eventloom.contrib.pydantic_v1` analog of `instructor.create_iterable()`;
  see that helper's docstring for how it decides an item is safe to emit.
- `company.metrics` (`replace`): `stream_client.create()` — the
  non-streaming convenience, one validated result, no partial yielding.
- `activity.log` (`append`): shared narration channel, same as
  `dashboard_app.py`.
- `company.competitor` (`merge`, **N concurrent instances of one event
  type**): three independent `.stream()` calls run concurrently, each
  filling in its own `CompanyProfile`-shaped object, each `emit()`-ing under
  its *own* `id` (`competitor-0`, `competitor-1`, ...) so the frontend can
  render three independently-progressing cards from a single registered
  event type. This mirrors the actual production pattern this module was
  ported from — `coachello-back`'s `roleplay_service.py` streams N
  evaluation "sections" concurrently the same way, one `id` per section.
  `dashboard_app.py` doesn't demonstrate this because it only ever needs one
  instance of each of its four types; eventloom's per-`id` sequence
  counters (`EventEmitter`) already support arbitrarily many concurrent
  instances of the same type with zero extra code — this is that support
  made visible.

Each task catches its own failure and reports it as an `activity.log` line,
same as `dashboard_app.py`, so one provider hiccup doesn't abort the others.
"""

from __future__ import annotations

import os
from typing import Any, List, Optional

import anyio
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from eventloom import EventEmitter, EventTypeRegistry
from eventloom.adapters.fastapi import emitter_dependency, to_sse_response
from eventloom.contrib.pydantic_v1 import BaseModel, stream_new_list_items
from eventloom.contrib.pydantic_v1.providers.openai import OpenAIStreamClient

# --- 1. Declare event types (Pydantic v1 models) -----------------------------


class CompanyProfile(BaseModel):
    name: Optional[str] = None
    industry: Optional[str] = None
    founded_year: Optional[int] = None
    headquarters: Optional[str] = None
    description: Optional[str] = None
    key_products: Optional[List[str]] = None


class Insight(BaseModel):
    title: str
    detail: str
    signal: str  # "positive" | "neutral" | "risk" — free text, not a v1
    # Literal/Enum: partial items arrive from stream_new_list_items only once
    # `is_complete` says they're done, so there's nothing to gain from
    # validating an in-progress Literal mid-stream the way there would be for
    # a field-by-field partial object.


class InsightsBatch(BaseModel):
    """Wrapper `stream_new_list_items` diffs against — there's no
    `create_iterable`-equivalent provider mode in this module (see its
    module docstring); a growing list field on one streamed object plus the
    helper is the whole mechanism."""

    insights: List[Insight] = []


class MetricsBreakdown(BaseModel):
    metric: str  # see dashboard_app.py's identical field for why this exists
    labels: List[str]
    values: List[float]


class LogLine(BaseModel):
    text: str


registry = EventTypeRegistry()
registry.register("company.profile", CompanyProfile, strategy="merge")
registry.register("company.insight", Insight, strategy="append")
registry.register("company.metrics", MetricsBreakdown, strategy="replace")
registry.register("activity.log", LogLine, strategy="append")
registry.register("company.competitor", CompanyProfile, strategy="merge")


# --- 2. LLM client (eventloom.contrib.pydantic_v1) ----------------------------

OPENAI_MODEL = os.environ.get("EVENTLOOM_LLM_MODEL", "gpt-4o-mini")
stream_client = OpenAIStreamClient()  # reads OPENAI_API_KEY from the environment

COMPANY = "Nimbus Systems"  # same fictional subject as dashboard_app.py
COMPETITORS = ["Aurora Cloud", "Vertex Compute", "Latticework AI"]  # for company.competitor


# --- 3. Wire up the endpoint ------------------------------------------------------

app = FastAPI(title="eventloom dashboard example (Pydantic v1)")

# Same CORS story as dashboard_app.py — see that file's comment for why.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

get_emitter = emitter_dependency(registry)


async def _stream_profile(emitter: EventEmitter) -> None:
    """Field-by-field partial streaming of a single object (`merge`) —
    identical mechanics to dashboard_app.py's `_stream_profile`, just against
    a Pydantic v1 model and eventloom.contrib.pydantic_v1's `.stream()`."""
    await emitter.emit("activity.log", LogLine(text=f"Requesting profile from {OPENAI_MODEL}..."), id="log-1")

    sent: dict[str, Any] = {}
    try:
        async for partial in stream_client.stream(
            model=OPENAI_MODEL,
            response_model=CompanyProfile,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Invent a profile for a fictional AI infrastructure startup called "
                        f"{COMPANY}: its industry, the year it was founded, its headquarters "
                        f"city, a two-sentence description, and 3-5 key products it sells."
                    ),
                }
            ],
        ):
            new_fields = {
                field: value
                for field, value in partial.dict(exclude_none=True).items()
                if sent.get(field) != value
            }
            if new_fields:
                sent.update(new_fields)
                await emitter.emit("company.profile", new_fields, id="profile-1")
        await emitter.emit("activity.log", LogLine(text=f"Profile complete ({len(sent)} fields)."), id="log-1")
    except Exception as exc:  # noqa: BLE001 - isolate this task's failure from the other tasks
        await emitter.emit("activity.log", LogLine(text=f"Profile request failed: {exc}"), id="log-1")
    finally:
        await emitter.emit("company.profile", {}, id="profile-1", done=True)


async def _stream_insights(emitter: EventEmitter) -> None:
    """Multi-object streaming (`append`) via `stream_new_list_items` — the
    eventloom.contrib.pydantic_v1 analog of dashboard_app.py's
    `create_iterable()`-based `_stream_insights`."""
    await emitter.emit("activity.log", LogLine(text="Requesting analyst insights..."), id="log-1")

    try:
        partials = stream_client.stream(
            model=OPENAI_MODEL,
            response_model=InsightsBatch,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Generate 3 to 4 distinct analyst insights about the fictional "
                        f"startup {COMPANY} for an investor dashboard. Each needs a short "
                        f"title, a 1-2 sentence supporting detail, and a `signal` of "
                        f"'positive', 'neutral', or 'risk'. Include at least one risk. "
                        f"Return them under an `insights` list."
                    ),
                }
            ],
        )

        count = 0
        async for insight in stream_new_list_items(
            partials,
            get_list=lambda p: p.insights,
            is_complete=lambda i: bool(getattr(i, "title", None) and getattr(i, "detail", None) and getattr(i, "signal", None)),
        ):
            count += 1
            await emitter.emit("company.insight", insight, id="insights")
            await emitter.emit("activity.log", LogLine(text=f"Insight #{count}: {insight.title}"), id="log-1")

        await emitter.emit("activity.log", LogLine(text=f"{count} insights received."), id="log-1")
    except Exception as exc:  # noqa: BLE001 - isolate this task's failure from the other tasks
        await emitter.emit("activity.log", LogLine(text=f"Insights request failed: {exc}"), id="log-1")


async def _stream_metrics(emitter: EventEmitter) -> None:
    """Non-streamed extraction (`replace`) via `stream_client.create()` — the
    eventloom.contrib.pydantic_v1 analog of dashboard_app.py's plain
    `instructor.create()`-based `_stream_metrics`."""
    await emitter.emit("activity.log", LogLine(text="Requesting metrics breakdown..."), id="log-1")

    try:
        metrics = await stream_client.create(
            model=OPENAI_MODEL,
            response_model=MetricsBreakdown,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"For the fictional startup {COMPANY}, invent ONE simple metric "
                        f"suitable for a bar chart — pick a single metric type (e.g. "
                        f"headcount by department, or revenue by product line) and name it "
                        f"in `metric`. Then break that *one* metric into 3-5 category "
                        f"labels, all sharing the same unit, with plausible numeric values. "
                        f"Do not mix different metric types into the same chart."
                    ),
                }
            ],
        )
        await emitter.emit("company.metrics", metrics, id="metrics-1", done=True)
        await emitter.emit("activity.log", LogLine(text="Metrics received."), id="log-1")
    except Exception as exc:  # noqa: BLE001 - isolate this task's failure from the other tasks
        await emitter.emit("activity.log", LogLine(text=f"Metrics request failed: {exc}"), id="log-1")


async def _stream_one_competitor(emitter: EventEmitter, name: str, idx: int) -> None:
    """One of N concurrent `company.competitor` streams — same field-by-field
    `merge` mechanics as `_stream_profile`, but parameterized per competitor
    and given its own `id` (`competitor-{idx}`) so N of these can run at once
    under one shared event type. See the module docstring's note on why this
    pattern (not present in dashboard_app.py) is the actual point of this
    example: it's what the module was ported out of production for."""
    sent: dict[str, Any] = {}
    try:
        async for partial in stream_client.stream(
            model=OPENAI_MODEL,
            response_model=CompanyProfile,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Invent a profile for a fictional competitor to {COMPANY} called "
                        f"{name}: its industry, the year it was founded, its headquarters "
                        f"city, a two-sentence description, and 3-5 key products it sells."
                    ),
                }
            ],
        ):
            new_fields = {
                field: value
                for field, value in partial.dict(exclude_none=True).items()
                if sent.get(field) != value
            }
            if new_fields:
                sent.update(new_fields)
                await emitter.emit("company.competitor", new_fields, id=f"competitor-{idx}")
        await emitter.emit("activity.log", LogLine(text=f"Competitor profile complete: {name}."), id="log-1")
    except Exception as exc:  # noqa: BLE001 - isolate this task's failure from the other tasks/competitors
        await emitter.emit("activity.log", LogLine(text=f"Competitor request failed ({name}): {exc}"), id="log-1")
    finally:
        await emitter.emit("company.competitor", {}, id=f"competitor-{idx}", done=True)


@app.get("/stream/dashboard")
async def dashboard_stream(emitter: EventEmitter = Depends(get_emitter)):
    async def run() -> None:
        await emitter.emit("activity.log", LogLine(text=f"Starting research on {COMPANY}..."), id="log-1")
        async with anyio.create_task_group() as tg:
            tg.start_soon(_stream_profile, emitter)
            tg.start_soon(_stream_insights, emitter)
            tg.start_soon(_stream_metrics, emitter)
            for idx, name in enumerate(COMPETITORS):
                tg.start_soon(_stream_one_competitor, emitter, name, idx)
        await emitter.emit("activity.log", LogLine(text="Research complete."), id="log-1")

    return to_sse_response(emitter, run=run)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
