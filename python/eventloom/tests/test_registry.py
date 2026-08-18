import pytest

from eventloom import DuplicateEventTypeError, EventTypeRegistry, UnknownEventTypeError

from ._models import ChartData, LogLine


def test_register_and_get():
    registry = EventTypeRegistry()
    registry.register("chart.data", ChartData, strategy="replace")

    spec = registry.get("chart.data")
    assert spec.type_name == "chart.data"
    assert spec.schema is ChartData
    assert spec.strategy == "replace"


def test_get_unknown_type_raises():
    registry = EventTypeRegistry()
    with pytest.raises(UnknownEventTypeError):
        registry.get("does.not.exist")


def test_register_same_type_twice_identically_is_idempotent():
    registry = EventTypeRegistry()
    registry.register("chart.data", ChartData, strategy="replace")
    registry.register("chart.data", ChartData, strategy="replace")  # no raise
    assert len(registry) == 1


def test_register_same_type_twice_with_different_schema_raises():
    registry = EventTypeRegistry()
    registry.register("thing", ChartData, strategy="replace")
    with pytest.raises(DuplicateEventTypeError):
        registry.register("thing", LogLine, strategy="replace")


def test_contains_and_iter():
    registry = EventTypeRegistry()
    registry.register("chart.data", ChartData)
    registry.register("log.line", LogLine, strategy="append")

    assert "chart.data" in registry
    assert "missing" not in registry
    assert {spec.type_name for spec in registry} == {"chart.data", "log.line"}
