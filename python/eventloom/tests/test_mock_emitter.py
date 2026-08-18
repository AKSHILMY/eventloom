from eventloom.testing import MockEmitter

from ._models import ChartData, LogLine


async def test_mock_emitter_records_emitted_envelopes(registry):
    emitter = MockEmitter(registry)
    await emitter.emit("chart.data", ChartData(labels=["Q1"], values=[1.0]), id="chart-1", done=True)
    await emitter.emit("log.line", LogLine(text="a"), id="log-1")
    await emitter.emit("log.line", LogLine(text="b"), id="log-1")

    assert [e.type for e in emitter.emitted] == ["chart.data", "log.line", "log.line"]
    assert [e.data.text for e in emitter.emitted_by_type("log.line")] == ["a", "b"]


async def test_mock_emitter_records_errors():
    from eventloom import EventTypeRegistry

    emitter = MockEmitter(EventTypeRegistry())
    await emitter.emit_error("failed", code="X")
    assert emitter.emitted[0].type == "__stream_error__"
