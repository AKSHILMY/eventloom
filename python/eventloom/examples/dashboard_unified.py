"""Unified comparison backend — run all four eventloom flows side by side.

Four modes, one file.  Start one instance per mode, each on its own port:

    python examples/dashboard_unified.py --mode manual-v1 --port 8001
    python examples/dashboard_unified.py --mode manual-v2 --port 8002
    python examples/dashboard_unified.py --mode auto-v1   --port 8003
    python examples/dashboard_unified.py --mode auto-v2   --port 8004

Then open the React frontend (typescript/examples/react-dashboard) — it
connects to all four ports simultaneously and renders the same fictional
company profile in four side-by-side panels.  All four panels fill in
identically because the SSE wire protocol never depends on which flow or
which Pydantic version produced the events.

Mode map
--------
manual-v1  OpenAIStreamClient + manual ``sent`` dict  (Pydantic v1)
manual-v2  instructor + manual ``sent`` dict           (Pydantic v2)
auto-v1    register_model + stream_model/stream_items  (Pydantic v1)
auto-v2    register_model + stream_model/stream_items  (Pydantic v2)

Prerequisites
-------------
    pip install "eventloom[examples-pydantic-v1]"   # covers all four modes
    export OPENAI_API_KEY=sk-...

Optional env vars
-----------------
    EVENTLOOM_OPENAI_MODEL   model name for v1 modes  (default: gpt-4o-mini)
    EVENTLOOM_LLM_MODEL      provider/model for v2    (default: openai/gpt-4o-mini)
"""

from __future__ import annotations

import argparse
import enum
import os
from typing import Any, List, Optional

import anyio
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from eventloom import EventEmitter, EventTypeRegistry
from eventloom.adapters.fastapi import emitter_dependency, to_sse_response
from eventloom.contrib.pydantic_v1 import BaseModel as V1Base
from eventloom.contrib.pydantic_v1 import stream_new_list_items
from pydantic.v1 import validator as v1_validator
from pydantic import BaseModel as V2Base

# ---------------------------------------------------------------------------
# CLI args — parsed at module load so schema classes can be at module scope
# (pydantic v1 models must be at module scope when ``from __future__ import
# annotations`` is active; defining them inside a function breaks field
# resolution for list-typed fields).
# ---------------------------------------------------------------------------

_parser = argparse.ArgumentParser(description="eventloom unified comparison backend")
_parser.add_argument(
    "--mode",
    required=True,
    choices=["manual-v1", "manual-v2", "auto-v1", "auto-v2", "complex-auto-v1"],
    help="Which flow to run",
)
_parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
_args = _parser.parse_args()

MODE: str = _args.mode
PORT: int = _args.port

# ---------------------------------------------------------------------------
# LLM config
# ---------------------------------------------------------------------------

COMPANY = "Nimbus Systems"

# v1 modes: model name only (OpenAIStreamClient takes "gpt-4o-mini", not "openai/…")
OPENAI_MODEL: str = os.environ.get("EVENTLOOM_OPENAI_MODEL", "gpt-4o-mini")

# v2 modes: full provider/model string understood by instructor.from_provider()
LLM_PROVIDER: str = os.environ.get("EVENTLOOM_LLM_MODEL", "openai/gpt-4o-mini")

LLM_MAX_TOKENS = 1024

# ---------------------------------------------------------------------------
# Schemas — ALL defined at module scope (required for pydantic v1 field
# resolution; harmless overhead for v2).  Prefixed V1*/V2* within this file
# to avoid collision; event type names registered in each registry are the
# same for all four modes so the frontend can use one shared renderer map.
# ---------------------------------------------------------------------------

# ── Pydantic v1 ──────────────────────────────────────────────────────────────


class V1CompanyProfile(V1Base):
    name: Optional[str] = None
    industry: Optional[str] = None
    founded_year: Optional[int] = None
    headquarters: Optional[str] = None
    description: Optional[str] = None
    key_products: Optional[List[str]] = None  # primitive list → no append sub-events


class V1Insight(V1Base):
    title: str
    detail: str
    signal: str  # "positive" | "neutral" | "risk"


class V1InsightsBatch(V1Base):
    """Batch wrapper for stream_items / stream_new_list_items (v1 pattern)."""
    insights: List[V1Insight] = []


class V1MetricsBreakdown(V1Base):
    metric: str
    labels: List[str]
    values: List[float]


class V1LogLine(V1Base):
    text: str


# ── Pydantic v1 — complex evaluation schema ───────────────────────────────────


class V1EvalSectionType(str, enum.Enum):
    basic     = "basic"
    framework = "framework"
    advanced  = "advanced"


class V1EvalLevel(str, enum.Enum):
    beginner     = "beginner"
    intermediate = "intermediate"
    expert       = "expert"


class V1EvalCriteria(V1Base):
    name: str = ""
    level: Optional[V1EvalLevel] = V1EvalLevel.intermediate
    improve: str = ""    # coaching tip — what to do better
    you_said: str = ""   # verbatim quote from the conversation
    stronger: str = ""   # rewritten stronger version

    # LLMs often capitalise enum values ("Intermediate", "Expert").
    # pre=True normalises the raw string before pydantic coerces it to the enum.
    @v1_validator("level", pre=True, always=True)
    @classmethod
    def _normalise_level(cls, v: object) -> object:
        return v.lower() if isinstance(v, str) else v


class V1EvalSection(V1Base):
    title: str = ""
    section_type: Optional[V1EvalSectionType] = V1EvalSectionType.basic
    criterias: List[V1EvalCriteria] = []

    @v1_validator("section_type", pre=True, always=True)
    @classmethod
    def _normalise_section_type(cls, v: object) -> object:
        return v.lower() if isinstance(v, str) else v


class V1EvaluationGrid(V1Base):
    """Top-level schema for the single-call evaluation stream.

    ``register_model("evaluation", V1EvaluationGrid)`` auto-derives:
    - ``"evaluation"``          → merge  (overall_score, description fill in at the end)
    - ``"evaluation.sections"`` → append (one complete V1EvalSection per new item)
    """
    sections: List[V1EvalSection] = []
    overall_score: Optional[int] = None   # 0–100; arrives via merge at the end
    description: str = ""                 # overall feedback paragraph


# ── Pydantic v2 ──────────────────────────────────────────────────────────────


class V2CompanyProfile(V2Base):
    name: str | None = None
    industry: str | None = None
    founded_year: int | None = None
    headquarters: str | None = None
    description: str | None = None
    key_products: list[str] | None = None  # primitive list → no append sub-events


class V2Insight(V2Base):
    title: str
    detail: str
    signal: str  # "positive" | "neutral" | "risk"


class V2MetricsBreakdown(V2Base):
    metric: str
    labels: list[str]
    values: list[float]


class V2LogLine(V2Base):
    text: str


# ---------------------------------------------------------------------------
# Registry setup — one registry per process (mode determines which schemas
# and which strategy variant to use)
# ---------------------------------------------------------------------------

registry = EventTypeRegistry()

if MODE == "manual-v1":
    # Manual: plain register() — no auto-derivation of sub-events
    registry.register("company.profile", V1CompanyProfile, strategy="merge")
    registry.register("company.insight", V1Insight, strategy="append")
    registry.register("company.metrics", V1MetricsBreakdown, strategy="replace")
    registry.register("activity.log", V1LogLine, strategy="append")

elif MODE == "manual-v2":
    registry.register("company.profile", V2CompanyProfile, strategy="merge")
    registry.register("company.insight", V2Insight, strategy="append")
    registry.register("company.metrics", V2MetricsBreakdown, strategy="replace")
    registry.register("activity.log", V2LogLine, strategy="append")

elif MODE == "auto-v1":
    # Auto: register_model() auto-derives event types from schema fields
    registry.register_model("company.profile", V1CompanyProfile)
    registry.register("company.insight", V1Insight, strategy="append")
    registry.register("company.metrics", V1MetricsBreakdown, strategy="replace")
    registry.register("activity.log", V1LogLine, strategy="append")

elif MODE == "auto-v2":
    registry.register_model("company.profile", V2CompanyProfile)
    registry.register("company.insight", V2Insight, strategy="append")
    registry.register("company.metrics", V2MetricsBreakdown, strategy="replace")
    registry.register("activity.log", V2LogLine, strategy="append")

else:  # complex-auto-v1
    # One register_model call — zero manual wiring.  Auto-derives:
    #   "evaluation"          → merge  (overall_score + description fill in at end)
    #   "evaluation.sections" → append (one complete V1EvalSection per new item)
    registry.register_model("evaluation", V1EvaluationGrid)
    registry.register("activity.log", V1LogLine, strategy="append")

# ---------------------------------------------------------------------------
# Run functions — one per mode.  Each is a standalone async function that
# receives an EventEmitter and drives three concurrent LLM tasks.
# Provider-specific imports are done lazily inside each function so that
# running --mode manual-v1 never requires the instructor package.
# ---------------------------------------------------------------------------

# ── manual-v1 ────────────────────────────────────────────────────────────────


async def run_manual_v1(emitter: EventEmitter) -> None:
    """Manual flow · Pydantic v1.

    Mirrors ``dashboard_app_pydantic_v1.py``: uses ``OpenAIStreamClient`` for
    partial streaming, a manual ``sent`` dict to track which fields have been
    emitted, and an explicit ``done=True`` in a ``finally`` block.
    """
    from eventloom.contrib.pydantic_v1.providers.openai import OpenAIStreamClient  # noqa: PLC0415

    stream_client = OpenAIStreamClient()

    async def _profile() -> None:
        await emitter.emit("activity.log", V1LogLine(text=f"[{MODE}] Requesting profile…"), id="log-1")
        sent: dict[str, Any] = {}
        try:
            async for partial in stream_client.stream(
                model=OPENAI_MODEL,
                response_model=V1CompanyProfile,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Invent a profile for a fictional AI infrastructure startup called "
                        f"{COMPANY}: its industry, the year it was founded, its headquarters "
                        f"city, a two-sentence description, and 3-5 key products it sells."
                    ),
                }],
            ):
                new_fields = {
                    k: v
                    for k, v in partial.dict(exclude_none=True).items()
                    if sent.get(k) != v
                }
                if new_fields:
                    sent.update(new_fields)
                    await emitter.emit("company.profile", new_fields, id="profile-1")
            await emitter.emit("activity.log", V1LogLine(text=f"Profile complete ({len(sent)} fields)."), id="log-1")
        except Exception as exc:  # noqa: BLE001
            await emitter.emit("activity.log", V1LogLine(text=f"Profile failed: {exc}"), id="log-1")
        finally:
            await emitter.emit("company.profile", {}, id="profile-1", done=True)

    async def _insights() -> None:
        await emitter.emit("activity.log", V1LogLine(text="Requesting insights…"), id="log-1")
        try:
            partials = stream_client.stream(
                model=OPENAI_MODEL,
                response_model=V1InsightsBatch,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Generate 3 to 4 distinct analyst insights about the fictional "
                        f"startup {COMPANY} for an investor dashboard. Each needs a short "
                        f"title, a 1-2 sentence detail, and a signal of 'positive', "
                        f"'neutral', or 'risk'. Return them under an `insights` list."
                    ),
                }],
            )
            count = 0
            async for insight in stream_new_list_items(
                partials,
                get_list=lambda p: p.insights,
                is_complete=lambda i: bool(
                    getattr(i, "title", None)
                    and getattr(i, "detail", None)
                    and getattr(i, "signal", None)
                ),
            ):
                count += 1
                await emitter.emit("company.insight", insight, id="insights")
                await emitter.emit("activity.log", V1LogLine(text=f"Insight #{count}: {insight.title}"), id="log-1")
            await emitter.emit("activity.log", V1LogLine(text=f"{count} insights received."), id="log-1")
        except Exception as exc:  # noqa: BLE001
            await emitter.emit("activity.log", V1LogLine(text=f"Insights failed: {exc}"), id="log-1")

    async def _metrics() -> None:
        await emitter.emit("activity.log", V1LogLine(text="Requesting metrics…"), id="log-1")
        try:
            metrics = await stream_client.create(
                model=OPENAI_MODEL,
                response_model=V1MetricsBreakdown,
                messages=[{
                    "role": "user",
                    "content": (
                        f"For the fictional startup {COMPANY}, invent ONE simple metric "
                        f"suitable for a bar chart — pick a single metric type and name it "
                        f"in `metric`. Then break it into 3-5 category labels with plausible "
                        f"numeric values."
                    ),
                }],
            )
            await emitter.emit("company.metrics", metrics, id="metrics-1", done=True)
            await emitter.emit("activity.log", V1LogLine(text="Metrics received."), id="log-1")
        except Exception as exc:  # noqa: BLE001
            await emitter.emit("activity.log", V1LogLine(text=f"Metrics failed: {exc}"), id="log-1")

    await emitter.emit("activity.log", V1LogLine(text=f"Research starting — {COMPANY} [{MODE}]…"), id="log-1")
    async with anyio.create_task_group() as tg:
        tg.start_soon(_profile)
        tg.start_soon(_insights)
        tg.start_soon(_metrics)
    await emitter.emit("activity.log", V1LogLine(text=f"Research complete [{MODE}]."), id="log-1")


# ── manual-v2 ────────────────────────────────────────────────────────────────


async def run_manual_v2(emitter: EventEmitter) -> None:
    """Manual flow · Pydantic v2.

    Mirrors ``dashboard_app.py``: uses ``instructor.from_provider`` for
    partial streaming, a manual ``sent`` dict, and an explicit ``done=True``
    in a ``finally`` block.
    """
    import instructor  # noqa: PLC0415

    llm = instructor.from_provider(LLM_PROVIDER, async_client=True)

    async def _profile() -> None:
        await emitter.emit("activity.log", V2LogLine(text=f"[{MODE}] Requesting profile…"), id="log-1")
        sent: dict[str, Any] = {}
        try:
            stream = llm.create_partial(
                response_model=V2CompanyProfile,
                max_tokens=LLM_MAX_TOKENS,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Invent a profile for a fictional AI infrastructure startup called "
                        f"{COMPANY}: its industry, the year it was founded, its headquarters "
                        f"city, a two-sentence description, and 3-5 key products it sells."
                    ),
                }],
            )
            async for partial in stream:
                new_fields = {
                    k: v
                    for k, v in partial.model_dump(exclude_none=True).items()
                    if sent.get(k) != v
                }
                if new_fields:
                    sent.update(new_fields)
                    await emitter.emit("company.profile", new_fields, id="profile-1")
            await emitter.emit("activity.log", V2LogLine(text=f"Profile complete ({len(sent)} fields)."), id="log-1")
        except Exception as exc:  # noqa: BLE001
            await emitter.emit("activity.log", V2LogLine(text=f"Profile failed: {exc}"), id="log-1")
        finally:
            await emitter.emit("company.profile", {}, id="profile-1", done=True)

    async def _insights() -> None:
        await emitter.emit("activity.log", V2LogLine(text="Requesting insights…"), id="log-1")
        try:
            stream = llm.create_iterable(
                response_model=V2Insight,
                max_tokens=LLM_MAX_TOKENS,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Generate 3 to 4 distinct analyst insights about the fictional "
                        f"startup {COMPANY} for an investor dashboard. Each needs a short "
                        f"title, a 1-2 sentence supporting detail, and a signal of "
                        f"'positive', 'neutral', or 'risk'. Include at least one risk."
                    ),
                }],
            )
            count = 0
            async for insight in stream:
                count += 1
                await emitter.emit("company.insight", insight, id="insights")
                await emitter.emit("activity.log", V2LogLine(text=f"Insight #{count}: {insight.title}"), id="log-1")
            await emitter.emit("activity.log", V2LogLine(text=f"{count} insights received."), id="log-1")
        except Exception as exc:  # noqa: BLE001
            await emitter.emit("activity.log", V2LogLine(text=f"Insights failed: {exc}"), id="log-1")

    async def _metrics() -> None:
        await emitter.emit("activity.log", V2LogLine(text="Requesting metrics…"), id="log-1")
        try:
            metrics = await llm.create(
                response_model=V2MetricsBreakdown,
                max_tokens=LLM_MAX_TOKENS,
                messages=[{
                    "role": "user",
                    "content": (
                        f"For the fictional startup {COMPANY}, invent ONE simple metric "
                        f"suitable for a bar chart — pick a single metric type and name it "
                        f"in `metric`. Then break it into 3-5 category labels with plausible "
                        f"numeric values."
                    ),
                }],
            )
            await emitter.emit("company.metrics", metrics, id="metrics-1", done=True)
            await emitter.emit("activity.log", V2LogLine(text="Metrics received."), id="log-1")
        except Exception as exc:  # noqa: BLE001
            await emitter.emit("activity.log", V2LogLine(text=f"Metrics failed: {exc}"), id="log-1")

    await emitter.emit("activity.log", V2LogLine(text=f"Research starting — {COMPANY} [{MODE}]…"), id="log-1")
    async with anyio.create_task_group() as tg:
        tg.start_soon(_profile)
        tg.start_soon(_insights)
        tg.start_soon(_metrics)
    await emitter.emit("activity.log", V2LogLine(text=f"Research complete [{MODE}]."), id="log-1")


# ── auto-v1 ──────────────────────────────────────────────────────────────────


async def run_auto_v1(emitter: EventEmitter) -> None:
    """Auto flow · Pydantic v1.

    Mirrors ``dashboard_app_auto_v1.py``: uses ``register_model`` (already
    called above) and the ``stream_model`` / ``stream_items`` helpers from
    ``eventloom.contrib.pydantic_v1`` — no manual ``sent`` dict, no explicit
    ``done=True``, no instructor.
    """
    from eventloom.contrib.pydantic_v1 import stream_items as _stream_items  # noqa: PLC0415
    from eventloom.contrib.pydantic_v1 import stream_model as _stream_model  # noqa: PLC0415
    from eventloom.contrib.pydantic_v1.providers.openai import OpenAIStreamClient  # noqa: PLC0415

    stream_client = OpenAIStreamClient()

    async def _profile() -> None:
        await emitter.emit("activity.log", V1LogLine(text=f"[{MODE}] Requesting profile…"), id="log-1")
        try:
            await _stream_model(
                emitter, "company.profile", V1CompanyProfile,
                client=stream_client,
                model=OPENAI_MODEL,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Invent a profile for a fictional AI infrastructure startup called "
                        f"{COMPANY}: its industry, the year it was founded, its headquarters "
                        f"city, a two-sentence description, and 3-5 key products it sells."
                    ),
                }],
                id="profile-1",
            )
            await emitter.emit("activity.log", V1LogLine(text="Profile complete."), id="log-1")
        except Exception as exc:  # noqa: BLE001
            await emitter.emit("activity.log", V1LogLine(text=f"Profile failed: {exc}"), id="log-1")

    async def _insights() -> None:
        await emitter.emit("activity.log", V1LogLine(text="Requesting insights…"), id="log-1")
        try:
            count = await _stream_items(
                emitter, "company.insight", V1Insight,
                client=stream_client,
                model=OPENAI_MODEL,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Generate 3 to 4 distinct analyst insights about the fictional "
                        f"startup {COMPANY}. Each needs a short title, a 1-2 sentence "
                        f"detail, and a signal of 'positive', 'neutral', or 'risk'. "
                        f"Return them under an `insights` list."
                    ),
                }],
                wrapper_schema=V1InsightsBatch,
                get_list=lambda p: p.insights,
                id="insights",
            )
            await emitter.emit("activity.log", V1LogLine(text=f"{count} insights received."), id="log-1")
        except Exception as exc:  # noqa: BLE001
            await emitter.emit("activity.log", V1LogLine(text=f"Insights failed: {exc}"), id="log-1")

    async def _metrics() -> None:
        await emitter.emit("activity.log", V1LogLine(text="Requesting metrics…"), id="log-1")
        try:
            metrics = await stream_client.create(
                model=OPENAI_MODEL,
                response_model=V1MetricsBreakdown,
                messages=[{
                    "role": "user",
                    "content": (
                        f"For the fictional startup {COMPANY}, invent ONE simple metric "
                        f"suitable for a bar chart — pick a single metric type and name it "
                        f"in `metric`. Then break it into 3-5 category labels with plausible "
                        f"numeric values."
                    ),
                }],
            )
            await emitter.emit("company.metrics", metrics, id="metrics-1", done=True)
            await emitter.emit("activity.log", V1LogLine(text="Metrics received."), id="log-1")
        except Exception as exc:  # noqa: BLE001
            await emitter.emit("activity.log", V1LogLine(text=f"Metrics failed: {exc}"), id="log-1")

    await emitter.emit("activity.log", V1LogLine(text=f"Research starting — {COMPANY} [{MODE}]…"), id="log-1")
    async with anyio.create_task_group() as tg:
        tg.start_soon(_profile)
        tg.start_soon(_insights)
        tg.start_soon(_metrics)
    await emitter.emit("activity.log", V1LogLine(text=f"Research complete [{MODE}]."), id="log-1")


# ── auto-v2 ──────────────────────────────────────────────────────────────────


async def run_auto_v2(emitter: EventEmitter) -> None:
    """Auto flow · Pydantic v2.

    Mirrors ``dashboard_app_instructor.py``: uses ``register_model`` (already
    called above) and the ``stream_model`` / ``stream_items`` helpers from
    ``eventloom.contrib.instructor`` — no manual ``sent`` dict, no explicit
    ``done=True``, no instructor client setup.
    """
    from eventloom.contrib.instructor import stream_items as _stream_items  # noqa: PLC0415
    from eventloom.contrib.instructor import stream_model as _stream_model  # noqa: PLC0415

    async def _profile() -> None:
        await emitter.emit("activity.log", V2LogLine(text=f"[{MODE}] Requesting profile…"), id="log-1")
        try:
            await _stream_model(
                emitter, "company.profile", V2CompanyProfile,
                provider_model=LLM_PROVIDER,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Invent a profile for a fictional AI infrastructure startup called "
                        f"{COMPANY}: its industry, the year it was founded, its headquarters "
                        f"city, a two-sentence description, and 3-5 key products it sells."
                    ),
                }],
                id="profile-1",
                max_tokens=LLM_MAX_TOKENS,
            )
            await emitter.emit("activity.log", V2LogLine(text="Profile complete."), id="log-1")
        except Exception as exc:  # noqa: BLE001
            await emitter.emit("activity.log", V2LogLine(text=f"Profile failed: {exc}"), id="log-1")

    async def _insights() -> None:
        await emitter.emit("activity.log", V2LogLine(text="Requesting insights…"), id="log-1")
        try:
            count = await _stream_items(
                emitter, "company.insight", V2Insight,
                provider_model=LLM_PROVIDER,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Generate 3 to 4 distinct analyst insights about the fictional "
                        f"startup {COMPANY} for an investor dashboard. Each needs a short "
                        f"title, a 1-2 sentence supporting detail, and a signal of "
                        f"'positive', 'neutral', or 'risk'. Include at least one risk."
                    ),
                }],
                id="insights",
                max_tokens=LLM_MAX_TOKENS,
            )
            await emitter.emit("activity.log", V2LogLine(text=f"{count} insights received."), id="log-1")
        except Exception as exc:  # noqa: BLE001
            await emitter.emit("activity.log", V2LogLine(text=f"Insights failed: {exc}"), id="log-1")

    async def _metrics() -> None:
        import instructor  # noqa: PLC0415

        llm = instructor.from_provider(LLM_PROVIDER, async_client=True)
        await emitter.emit("activity.log", V2LogLine(text="Requesting metrics…"), id="log-1")
        try:
            metrics = await llm.create(
                response_model=V2MetricsBreakdown,
                max_tokens=LLM_MAX_TOKENS,
                messages=[{
                    "role": "user",
                    "content": (
                        f"For the fictional startup {COMPANY}, invent ONE simple metric "
                        f"suitable for a bar chart — pick a single metric type and name it "
                        f"in `metric`. Then break it into 3-5 category labels with plausible "
                        f"numeric values."
                    ),
                }],
            )
            await emitter.emit("company.metrics", metrics, id="metrics-1", done=True)
            await emitter.emit("activity.log", V2LogLine(text="Metrics received."), id="log-1")
        except Exception as exc:  # noqa: BLE001
            await emitter.emit("activity.log", V2LogLine(text=f"Metrics failed: {exc}"), id="log-1")

    await emitter.emit("activity.log", V2LogLine(text=f"Research starting — {COMPANY} [{MODE}]…"), id="log-1")
    async with anyio.create_task_group() as tg:
        tg.start_soon(_profile)
        tg.start_soon(_insights)
        tg.start_soon(_metrics)
    await emitter.emit("activity.log", V2LogLine(text=f"Research complete [{MODE}]."), id="log-1")


# ── complex-auto-v1 ──────────────────────────────────────────────────────────


async def run_complex_auto_v1(emitter: EventEmitter) -> None:
    """Single-call auto streaming of a deeply-nested evaluation schema.

    This is the entire developer-facing code for complex-auto-v1:

        registry.register_model("evaluation", V1EvaluationGrid)

        await stream_model(emitter, "evaluation", V1EvaluationGrid,
                           client=client, model=model, messages=[prompt])

    ``register_model`` auto-derives ``"evaluation.sections"`` (append) so each
    completed section is emitted as a separate event.  Sections arrive one by
    one as the LLM writes them; each carries all its criteria fully populated.
    ``overall_score`` and ``description`` stream in via the ``"evaluation"``
    merge event at the end.
    """
    from eventloom.contrib.pydantic_v1 import stream_model as v1_stream_model  # noqa: PLC0415
    from eventloom.contrib.pydantic_v1.providers.openai import OpenAIStreamClient  # noqa: PLC0415

    client = OpenAIStreamClient()
    await emitter.emit("activity.log", V1LogLine(text="Generating evaluation…"), id="log-1")

    await v1_stream_model(
        emitter,
        "evaluation",
        V1EvaluationGrid,
        client=client,
        model=OPENAI_MODEL,
        messages=[{
            "role": "user",
            "content": (
                "You are an expert sales coach. A sales rep just completed a roleplay "
                "discovery call with a prospect for a SaaS CRM product.\n\n"
                "Evaluate their performance. Produce exactly 4 sections: "
                "1) Communication Skills (section_type: basic), "
                "2) Needs Discovery Framework (section_type: framework), "
                "3) Objection Handling (section_type: advanced), "
                "4) Closing Technique (section_type: advanced).\n\n"
                "Each section must have exactly 3 criteria. Each criterion needs: "
                "name (short, 3-6 words), "
                "level (one of: beginner / intermediate / expert), "
                "improve (1-2 sentence coaching tip), "
                "you_said (a realistic verbatim quote from the rep), "
                "stronger (a rewritten stronger version of that quote).\n\n"
                "After all sections, set overall_score (integer 0-100) and "
                "description (2-3 sentence overall coaching summary)."
            ),
        }],
        id="eval-1",
    )

    await emitter.emit("activity.log", V1LogLine(text="Evaluation complete."), id="log-1")


# ---------------------------------------------------------------------------
# Mode dispatch
# ---------------------------------------------------------------------------

_RUN_FN = {
    "manual-v1":       run_manual_v1,
    "manual-v2":       run_manual_v2,
    "auto-v1":         run_auto_v1,
    "auto-v2":         run_auto_v2,
    "complex-auto-v1": run_complex_auto_v1,
}[MODE]

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title=f"eventloom unified [{MODE}]")

app.add_middleware(
    CORSMiddleware,
    # All four instances need the same CORS origin so the single frontend can
    # reach all four ports.
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

_get_emitter = emitter_dependency(registry)


@app.get("/stream/dashboard")
async def dashboard_stream(emitter: EventEmitter = Depends(_get_emitter)):
    async def run() -> None:
        await _RUN_FN(emitter)

    return to_sse_response(emitter, run=run)


@app.get("/registry")
async def registry_info() -> dict:
    """Inspect what event types this mode registered."""
    return {
        "mode": MODE,
        "port": PORT,
        "event_types": [
            {"type": spec.type_name, "schema": spec.schema.__name__, "strategy": spec.strategy}
            for spec in registry
        ],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="debug")
