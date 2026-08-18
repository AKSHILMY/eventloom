"""In-memory emitter for unit tests — no HTTP, no adapter, no event loop
plumbing required beyond `await`.

Use this to unit-test the business logic that decides *what* to emit
(e.g. a function that runs a DB query and emits `chart.data`) without
spinning up a FastAPI app or an SSE client.

    async def test_dashboard_emits_chart_data():
        registry = EventTypeRegistry()
        registry.register("chart.data", ChartData, strategy="replace")

        emitter = MockEmitter(registry)
        await run_dashboard_logic(emitter)  # your app code, takes an EventEmitter

        assert emitter.emitted[0].type == "chart.data"
        assert emitter.emitted[0].data.labels == ["Q1", "Q2"]
"""

from __future__ import annotations

from ..core.emitter import EventEmitter
from ..core.envelope import StreamEnvelope
from ..core.registry import EventTypeRegistry


class MockEmitter(EventEmitter):
    """An `EventEmitter` that also records every emitted envelope in-order
    on `self.emitted`, so tests can assert on it directly without draining
    `events()` themselves.
    """

    def __init__(self, registry: EventTypeRegistry, group_id: str | None = None) -> None:
        super().__init__(registry, group_id=group_id)
        self.emitted: list[StreamEnvelope] = []

    async def emit(self, *args: object, **kwargs: object) -> StreamEnvelope:  # type: ignore[override]
        envelope = await super().emit(*args, **kwargs)  # type: ignore[arg-type]
        self.emitted.append(envelope)
        return envelope

    async def emit_error(self, *args: object, **kwargs: object) -> StreamEnvelope:  # type: ignore[override]
        envelope = await super().emit_error(*args, **kwargs)  # type: ignore[arg-type]
        self.emitted.append(envelope)
        return envelope

    def emitted_by_type(self, type_name: str) -> list[StreamEnvelope]:
        return [e for e in self.emitted if e.type == type_name]
