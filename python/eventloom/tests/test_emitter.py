import pytest
from pydantic import ValidationError

from eventloom import EmitterClosedError, EventEmitter, UnknownEventTypeError

from ._models import ChartData, LogLine


async def test_emit_validates_and_wraps_in_envelope(registry):
    emitter = EventEmitter(registry)
    envelope = await emitter.emit(
        "chart.data", ChartData(labels=["Q1"], values=[1.0]), id="chart-1", done=True
    )

    assert envelope.type == "chart.data"
    assert envelope.id == "chart-1"
    assert envelope.seq == 0
    assert envelope.strategy == "replace"
    assert envelope.done is True
    assert envelope.data.labels == ["Q1"]


async def test_emit_accepts_plain_dict_and_validates_it(registry):
    emitter = EventEmitter(registry)
    envelope = await emitter.emit("chart.data", {"labels": ["Q1"], "values": [1.0]}, id="chart-1")
    assert isinstance(envelope.data, ChartData)


async def test_emit_rejects_dict_that_fails_schema_validation(registry):
    emitter = EventEmitter(registry)
    with pytest.raises(ValidationError):
        await emitter.emit("chart.data", {"labels": "not-a-list"}, id="chart-1")


async def test_emit_unknown_type_raises(registry):
    emitter = EventEmitter(registry)
    with pytest.raises(UnknownEventTypeError):
        await emitter.emit("nope", {}, id="x")


async def test_seq_increments_per_id_independently(registry):
    emitter = EventEmitter(registry)
    e1 = await emitter.emit("log.line", LogLine(text="a"), id="log-1")
    e2 = await emitter.emit("log.line", LogLine(text="b"), id="log-1")
    e3 = await emitter.emit("log.line", LogLine(text="c"), id="log-2")

    assert (e1.seq, e2.seq) == (0, 1)
    assert e3.seq == 0  # different id, independent counter


async def test_events_yields_emitted_envelopes_in_order_then_stops_on_close(registry):
    emitter = EventEmitter(registry)
    await emitter.emit("log.line", LogLine(text="a"), id="log-1")
    await emitter.emit("log.line", LogLine(text="b"), id="log-1")
    emitter.close()

    received = [e async for e in emitter.events()]
    assert [e.data.text for e in received] == ["a", "b"]


async def test_emit_after_close_raises(registry):
    emitter = EventEmitter(registry)
    emitter.close()
    with pytest.raises(EmitterClosedError):
        await emitter.emit("log.line", LogLine(text="a"), id="log-1")


async def test_emit_error_produces_stream_error_envelope(registry):
    emitter = EventEmitter(registry)
    envelope = await emitter.emit_error("db unreachable", code="DBError")

    assert envelope.type == "__stream_error__"
    assert envelope.done is True
    assert envelope.data.message == "db unreachable"
    assert envelope.data.code == "DBError"


async def test_context_manager_closes_emitter(registry):
    async with EventEmitter(registry) as emitter:
        await emitter.emit("log.line", LogLine(text="a"), id="log-1")

    received = [e async for e in emitter.events()]
    assert len(received) == 1


# --- Pydantic-v1-style schemas (eventloom.contrib.pydantic_v1) --------------


async def test_emit_accepts_dict_against_v1_registered_schema():
    from pydantic.v1 import BaseModel as V1BaseModel

    from eventloom import EventTypeRegistry

    class V1ChartData(V1BaseModel):
        labels: list[str]
        values: list[float]

    v1_registry = EventTypeRegistry()
    v1_registry.register("chart.data", V1ChartData, strategy="replace")

    emitter = EventEmitter(v1_registry)
    envelope = await emitter.emit("chart.data", {"labels": ["Q1"], "values": [1.0]}, id="chart-1")

    assert isinstance(envelope.data, V1ChartData)
    assert envelope.data.labels == ["Q1"]


async def test_emit_rejects_dict_that_fails_v1_schema_validation():
    from pydantic.v1 import BaseModel as V1BaseModel
    from pydantic.v1 import ValidationError as V1ValidationError

    from eventloom import EventTypeRegistry

    class V1ChartData(V1BaseModel):
        labels: list[str]
        values: list[float]

    v1_registry = EventTypeRegistry()
    v1_registry.register("chart.data", V1ChartData, strategy="replace")

    emitter = EventEmitter(v1_registry)
    with pytest.raises(V1ValidationError):
        await emitter.emit("chart.data", {"labels": "not-a-list"}, id="chart-1")
