"""Runnable example: a FastAPI backend emitting three different event types
with three different merge strategies, over one SSE endpoint.

    pip install "eventloom[fastapi]" uvicorn
    python examples/dashboard_app.py
    curl -N http://localhost:8000/stream/dashboard

This mirrors "Build sequence" phases 5-6 in the project plan: a real endpoint
using more than one event type/component, proving the abstraction generalizes
instead of being special-cased for a single chart widget.
"""

from __future__ import annotations

import asyncio

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from eventloom import EventEmitter, EventTypeRegistry
from eventloom.adapters.fastapi import emitter_dependency, to_sse_response

# --- 1. Declare event types (this is `myapp/events.py` in a real app) -----------


class ChartData(BaseModel):
    labels: list[str]
    values: list[float]


class UserProfile(BaseModel):
    name: str | None = None
    bio: str | None = None


class LogLine(BaseModel):
    text: str


registry = EventTypeRegistry()
registry.register("chart.data", ChartData, strategy="replace")
registry.register("user.partial", UserProfile, strategy="merge")
registry.register("log.line", LogLine, strategy="append")


# --- 2. Wire up the endpoint ------------------------------------------------------

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


@app.get("/stream/dashboard")
async def dashboard_stream(emitter: EventEmitter = Depends(get_emitter)):
    async def run() -> None:
        # A discrete event: fully replaces any prior "chart-1" data.
        await emitter.emit(
            "chart.data",
            ChartData(labels=["Q1", "Q2", "Q3"], values=[120.0, 150.0, 90.0]),
            id="chart-1",
            done=True,
        )

        # A partial object streaming in field-by-field — each emit merges
        # into the existing "profile-1" object instead of replacing it.
        await emitter.emit("user.partial", UserProfile(name="Ada Lovelace"), id="profile-1")
        await asyncio.sleep(0.05)
        await emitter.emit(
            "user.partial",
            UserProfile(bio="Mathematician & first programmer"),
            id="profile-1",
            done=True,
        )

        # Append-strategy log lines streaming in one at a time.
        for line in ["Fetching data...", "Running aggregation...", "Done."]:
            await emitter.emit("log.line", LogLine(text=line), id="log-1")
            await asyncio.sleep(0.05)

    return to_sse_response(emitter, run=run)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
