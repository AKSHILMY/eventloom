import json

import httpx
import pytest
from fastapi import Depends, FastAPI

from eventloom import EventEmitter
from eventloom.adapters.fastapi import emitter_dependency, to_sse_response

from ._models import ChartData, LogLine


def build_app(registry):
    app = FastAPI()
    get_emitter = emitter_dependency(registry)

    @app.get("/stream/dashboard")
    async def dashboard_stream(emitter: EventEmitter = Depends(get_emitter)):
        async def run():
            await emitter.emit(
                "chart.data", ChartData(labels=["Q1", "Q2"], values=[1.0, 2.0]), id="chart-1", done=True
            )
            await emitter.emit("log.line", LogLine(text="hello"), id="log-1")
            await emitter.emit("log.line", LogLine(text="world"), id="log-1")

        return to_sse_response(emitter, run=run)

    @app.get("/stream/broken")
    async def broken_stream(emitter: EventEmitter = Depends(get_emitter)):
        async def run():
            await emitter.emit("log.line", LogLine(text="before crash"), id="log-1")
            raise RuntimeError("boom")

        return to_sse_response(emitter, run=run)

    return app


async def _collect_data_lines(app, path: str) -> list[dict]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream("GET", path) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")

            envelopes = []
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    envelopes.append(json.loads(line[len("data: ") :]))
            return envelopes


async def test_sse_response_streams_envelopes_in_order(registry):
    app = build_app(registry)
    envelopes = await _collect_data_lines(app, "/stream/dashboard")

    assert [e["type"] for e in envelopes] == ["chart.data", "log.line", "log.line"]
    assert envelopes[0]["data"] == {"labels": ["Q1", "Q2"], "values": [1.0, 2.0]}
    assert envelopes[0]["strategy"] == "replace"
    assert envelopes[1]["strategy"] == "append"
    assert envelopes[1]["seq"] == 0
    assert envelopes[2]["seq"] == 1


async def test_sse_response_emits_stream_error_on_exception(registry):
    app = build_app(registry)
    envelopes = await _collect_data_lines(app, "/stream/broken")

    assert envelopes[0]["type"] == "log.line"
    assert envelopes[-1]["type"] == "__stream_error__"
    assert envelopes[-1]["data"]["message"] == "boom"
    assert envelopes[-1]["data"]["code"] == "RuntimeError"


async def test_sse_headers_disable_proxy_buffering(registry):
    app = build_app(registry)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream("GET", "/stream/dashboard") as response:
            assert response.headers["cache-control"] == "no-cache"
            assert response.headers["x-accel-buffering"] == "no"
            async for _ in response.aiter_lines():
                pass  # drain
