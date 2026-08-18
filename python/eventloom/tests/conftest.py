import pytest

from eventloom import EventTypeRegistry

from ._models import ChartData, LogLine, UserProfile


@pytest.fixture()
def registry() -> EventTypeRegistry:
    reg = EventTypeRegistry()
    reg.register("chart.data", ChartData, strategy="replace")
    reg.register("user.partial", UserProfile, strategy="merge")
    reg.register("log.line", LogLine, strategy="append")
    return reg
