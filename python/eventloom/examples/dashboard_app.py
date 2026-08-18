"""Runnable example: a FastAPI backend researching a fictional startup with
three *concurrent* LLM calls — via `instructor` — and streaming the results
over one SSE endpoint as four distinct, differently-strategied event types.

    pip install "eventloom[examples]"
    export OPENAI_API_KEY=sk-...          # or point EVENTLOOM_LLM_MODEL elsewhere
    python examples/dashboard_app.py
    curl -N http://localhost:8000/stream/dashboard

Three instructor call shapes, three eventloom strategies, run at the same time
via one `anyio.create_task_group()` so they visibly interleave on the wire:

- `company.profile` (`merge`): `instructor.create_partial()` yields a full
  `CompanyProfile` on every chunk with whatever fields the model has
  generated *so far* already filled in. Each `emitter.emit()` call below only
  carries the fields that are new since the last chunk — that's what lets the
  frontend genuinely fill in a profile card field-by-field instead of
  swapping in a finished object.
- `company.insight` (`append`): `instructor.create_iterable()` streams
  multiple *complete, validated* objects, one per finished item — a
  different instructor mode than the field-by-field partial above, and a
  natural fit for an append-only feed.
- `company.metrics` (`replace`): a single non-streamed `instructor.create()`
  call — the plain structured-extraction mode most instructor examples start
  with, included here for contrast with the two streaming modes above.

`activity.log` (`append`) isn't LLM-driven itself; it's a shared narration
channel all three tasks write status lines into, so the frontend's log panel
shows real interleaved progress across three independent async LLM calls
multiplexed over a single SSE connection — the thing eventloom is actually
for.

Each of the three tasks catches its own failure (e.g. a missing/bad API key)
and reports it as an `activity.log` line rather than letting it propagate: an
uncaught exception from one task inside the shared `anyio.create_task_group()`
would abort the *other two* as well and surface as one opaque
`__stream_error__` for the whole stream, instead of "two of three panels
loaded fine, one provider call failed."

Swap `EVENTLOOM_LLM_MODEL` to any instructor-supported provider string, e.g.
"anthropic/claude-haiku-4-5-latest" (needs `ANTHROPIC_API_KEY`), "openai/gpt-4o-mini"
(default, needs `OPENAI_API_KEY`) — see https://python.useinstructor.com/integrations/
for the full list and each provider's expected env var.
"""

from __future__ import annotations

import os
from typing import Any

import anyio
import instructor
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from eventloom import EventEmitter, EventTypeRegistry
from eventloom.adapters.fastapi import emitter_dependency, to_sse_response

# --- 1. Declare event types (this is `myapp/events.py` in a real app) -----------


class CompanyProfile(BaseModel):
    name: str | None = None
    industry: str | None = None
    founded_year: int | None = None
    headquarters: str | None = None
    description: str | None = None
    key_products: list[str] | None = None


class Insight(BaseModel):
    title: str
    detail: str
    signal: str  # "positive" | "neutral" | "risk" — free text, not Literal:
    # a Literal field mid-partial-generation can't validate an incomplete
    # string, and these arrive fully-formed (Iterable streaming) anyway, so
    # there's nothing to gain from the extra `PartialLiteralMixin` machinery
    # instructor requires for partial Literal fields.


class MetricsBreakdown(BaseModel):
    metric: str  # what's being measured, e.g. "Headcount by department" —
    # without this, nothing stops the model from returning `labels` that are
    # each a *different* metric (headcount, revenue, a satisfaction score...)
    # sharing one chart with no common unit, which is exactly what happened
    # without this field: see the prompt below.
    labels: list[str]
    values: list[float]


class LogLine(BaseModel):
    text: str


registry = EventTypeRegistry()
registry.register("company.profile", CompanyProfile, strategy="merge")
registry.register("company.insight", Insight, strategy="append")
registry.register("company.metrics", MetricsBreakdown, strategy="replace")
registry.register("activity.log", LogLine, strategy="append")


# --- 2. LLM client (instructor) ----------------------------------------------

LLM_MODEL = os.environ.get("EVENTLOOM_LLM_MODEL", "openai/gpt-4o-mini")
llm_client = instructor.from_provider(LLM_MODEL, async_client=True)
LLM_MAX_TOKENS = 1024  # Anthropic's create_partial requires this explicitly;
# harmless to pass for every provider, so it's shared across all three calls
# below rather than special-cased per provider.

COMPANY = "Nimbus Systems"  # the fictional subject all three LLM calls research


# --- 3. Wire up the endpoint ------------------------------------------------------

app = FastAPI(title="eventloom dashboard example")

# The example React app (typescript/examples/react-dashboard) talks to this
# server cross-origin (:5173 -> :8000) directly, deliberately *not* through a
# dev-server proxy. A same-origin proxy setup can pick up unrelated cookies
# other local apps have set broadly on `localhost` (e.g. an oversized session
# token), which some dev proxies (Vite's included) choke on with an opaque
# 500 before the request ever reaches this server. Plain CORS sidesteps that
# entirely — and since `StreamConnection` doesn't send credentials by
# default, no cookies cross the boundary regardless.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

get_emitter = emitter_dependency(registry)


async def _stream_profile(emitter: EventEmitter) -> None:
    """Field-by-field partial streaming of a single object (`merge`).

    Runs inside the same task group as `_stream_insights`/`_stream_metrics`;
    catches its own failures (e.g. a bad API key) instead of propagating,
    so one provider hiccup doesn't take down the other two panels — see the
    module docstring's note on why each task guards itself rather than
    relying on `to_sse_response`'s outer catch-all."""
    await emitter.emit("activity.log", LogLine(text=f"Requesting profile from {LLM_MODEL}..."), id="log-1")

    sent: dict[str, Any] = {}
    try:
        # `create_partial` is itself an async generator (not a coroutine you
        # await first) — call it directly and iterate.
        stream = llm_client.create_partial(
            response_model=CompanyProfile,
            max_tokens=LLM_MAX_TOKENS,
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
        )
        async for partial in stream:
            # Only emit fields that are new/changed since the last chunk —
            # this is what keeps each envelope a minimal delta instead of
            # re-sending the whole (mostly-still-null) object every time.
            new_fields = {
                field: value
                for field, value in partial.model_dump(exclude_none=True).items()
                if sent.get(field) != value
            }
            if new_fields:
                sent.update(new_fields)
                await emitter.emit("company.profile", new_fields, id="profile-1")
        await emitter.emit("activity.log", LogLine(text=f"Profile complete ({len(sent)} fields)."), id="log-1")
    except Exception as exc:  # noqa: BLE001 - isolate this task's failure from the other two
        await emitter.emit("activity.log", LogLine(text=f"Profile request failed: {exc}"), id="log-1")
    finally:
        # Marks the card "done" (stops the "(streaming…)" label) whether it
        # finished, partially filled, or failed before a single field arrived.
        await emitter.emit("company.profile", {}, id="profile-1", done=True)


async def _stream_insights(emitter: EventEmitter) -> None:
    """Multi-object streaming (`append`): each yielded item is a complete,
    already-validated `Insight` — a different instructor mode than the
    field-by-field partial streaming in `_stream_profile`. Guards its own
    failure the same way `_stream_profile` does (see its docstring)."""
    await emitter.emit("activity.log", LogLine(text="Requesting analyst insights..."), id="log-1")

    try:
        # `create_iterable` (also an async generator — no `await` before
        # iterating, same as `create_partial` above) yields one *complete,
        # validated* Insight per finished item, not a partial one.
        stream = llm_client.create_iterable(
            response_model=Insight,
            max_tokens=LLM_MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Generate 3 to 4 distinct analyst insights about the fictional "
                        f"startup {COMPANY} for an investor dashboard. Each needs a short "
                        f"title, a 1-2 sentence supporting detail, and a `signal` of "
                        f"'positive', 'neutral', or 'risk'. Include at least one risk."
                    ),
                }
            ],
        )

        count = 0
        async for insight in stream:
            count += 1
            await emitter.emit("company.insight", insight, id="insights")
            await emitter.emit("activity.log", LogLine(text=f"Insight #{count}: {insight.title}"), id="log-1")

        await emitter.emit("activity.log", LogLine(text=f"{count} insights received."), id="log-1")
    except Exception as exc:  # noqa: BLE001 - isolate this task's failure from the other two
        await emitter.emit("activity.log", LogLine(text=f"Insights request failed: {exc}"), id="log-1")


async def _stream_metrics(emitter: EventEmitter) -> None:
    """A single, non-streamed instructor extraction (`replace`) — the plain
    `response_model=` mode most instructor examples start with, run here
    alongside the two streaming modes above for contrast. Guards its own
    failure the same way `_stream_profile` does (see its docstring)."""
    await emitter.emit("activity.log", LogLine(text="Requesting metrics breakdown..."), id="log-1")

    try:
        metrics = await llm_client.create(
            response_model=MetricsBreakdown,
            max_tokens=LLM_MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"For the fictional startup {COMPANY}, invent ONE simple metric "
                        f"suitable for a bar chart — pick a single metric type (e.g. "
                        f"headcount by department, or revenue by product line) and name it "
                        f"in `metric`. Then break that *one* metric into 3-5 category "
                        f"labels, all sharing the same unit, with plausible numeric values. "
                        f"Do not mix different metric types (e.g. headcount and revenue and "
                        f"a satisfaction score) into the same chart."
                    ),
                }
            ],
        )
        await emitter.emit("company.metrics", metrics, id="metrics-1", done=True)
        await emitter.emit("activity.log", LogLine(text="Metrics received."), id="log-1")
    except Exception as exc:  # noqa: BLE001 - isolate this task's failure from the other two
        await emitter.emit("activity.log", LogLine(text=f"Metrics request failed: {exc}"), id="log-1")


@app.get("/stream/dashboard")
async def dashboard_stream(emitter: EventEmitter = Depends(get_emitter)):
    async def run() -> None:
        await emitter.emit("activity.log", LogLine(text=f"Starting research on {COMPANY}..."), id="log-1")
        # All three LLM calls run concurrently — the activity log below
        # shows their progress lines genuinely interleaved, not run in
        # sequence, which is the point of multiplexing them over one SSE
        # connection instead of three separate requests.
        async with anyio.create_task_group() as tg:
            tg.start_soon(_stream_profile, emitter)
            tg.start_soon(_stream_insights, emitter)
            tg.start_soon(_stream_metrics, emitter)
        await emitter.emit("activity.log", LogLine(text="Research complete."), id="log-1")

    return to_sse_response(emitter, run=run)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
