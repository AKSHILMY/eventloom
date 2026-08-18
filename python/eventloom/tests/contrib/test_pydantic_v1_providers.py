"""Tests for eventloom.contrib.pydantic_v1.providers.base.ProviderStreamClient
— subclassed directly with canned `_raw_token_stream` chunks, so no LLM SDK
install is required. A separate, SDK-gated section below exercises
OpenAIStreamClient/AnthropicStreamClient's pure (no-network) methods only
when those SDKs happen to be installed.
"""

from typing import Any, AsyncGenerator, Dict, List, Optional, Type

import pytest

from eventloom.contrib.pydantic_v1 import BaseModel
from eventloom.contrib.pydantic_v1.errors import PartialStreamValidationError
from eventloom.contrib.pydantic_v1.providers.base import ProviderStreamClient


class Widget(BaseModel):
    name: str
    count: int


class _FakeStreamClient(ProviderStreamClient):
    """Replays canned raw-token chunks instead of calling a real LLM."""

    def __init__(self, chunks: List[str]) -> None:
        self._chunks = chunks

    def _build_tools_payload(self, model_cls: Type[BaseModel]) -> Any:
        return None

    def _build_request_kwargs(
        self, model: str, messages: List[Dict[str, str]], tools_payload: Any, **kwargs: Any
    ) -> Dict[str, Any]:
        return {}

    async def _raw_token_stream(self, **request_kwargs: Any) -> AsyncGenerator[str, None]:
        for chunk in self._chunks:
            yield chunk


def _complete_widget_chunks() -> List[str]:
    # Split a complete JSON object across several small token deltas.
    full = '{"name": "Gadget", "count": 3}'
    return [full[i : i + 4] for i in range(0, len(full), 4)]


async def test_intermediate_yields_stay_lenient_and_unvalidated():
    client = _FakeStreamClient(['{"name": "Ga'])  # deliberately incomplete, no final flush reached
    partials = [p async for p in client.stream(model="x", response_model=Widget, messages=[], validate_final=False)]
    assert len(partials) == 1
    assert partials[0].name == "Ga"
    assert not hasattr(partials[0], "count") or "count" not in partials[0].__fields_set__


async def test_final_yield_is_validated_and_reflects_complete_data():
    client = _FakeStreamClient(_complete_widget_chunks())
    partials = [p async for p in client.stream(model="x", response_model=Widget, messages=[])]
    final = partials[-1]
    assert final.name == "Gadget"
    assert final.count == 3
    # A real validating constructor sets every field, not just streamed ones.
    assert final.__fields_set__ == {"name", "count"}


async def test_validate_final_false_suppresses_the_extra_yield():
    client = _FakeStreamClient(_complete_widget_chunks())
    with_validation = [p async for p in client.stream(model="x", response_model=Widget, messages=[], validate_final=True)]
    without_validation = [
        p async for p in client.stream(model="x", response_model=Widget, messages=[], validate_final=False)
    ]
    assert len(with_validation) == len(without_validation) + 1


async def test_malformed_final_payload_raises_partial_stream_validation_error():
    # "count" never arrives as a valid int — final parse_obj() should fail.
    client = _FakeStreamClient(['{"name": "Gadget", "count": "not-a-number"}'])
    with pytest.raises(PartialStreamValidationError):
        async for _ in client.stream(model="x", response_model=Widget, messages=[]):
            pass


async def test_unparseable_final_stream_raises_partial_stream_validation_error():
    client = _FakeStreamClient(['not json at all \\'])
    with pytest.raises(PartialStreamValidationError):
        async for _ in client.stream(model="x", response_model=Widget, messages=[]):
            pass


async def test_create_returns_just_the_final_validated_object():
    client = _FakeStreamClient(_complete_widget_chunks())
    result = await client.create(model="x", response_model=Widget, messages=[])
    assert isinstance(result, Widget)
    assert (result.name, result.count) == ("Gadget", 3)


async def test_create_raises_if_no_data_received():
    client = _FakeStreamClient([])
    with pytest.raises(PartialStreamValidationError):
        await client.create(model="x", response_model=Widget, messages=[])


# --- SDK-gated: pure (no-network) methods on the real provider clients ------


def test_openai_build_tools_payload_shape():
    openai = pytest.importorskip("openai")
    from eventloom.contrib.pydantic_v1.providers.openai import OpenAIStreamClient

    client = OpenAIStreamClient(client=openai.AsyncOpenAI(api_key="test-key"))
    payload = client._build_tools_payload(Widget)
    assert payload[0]["type"] == "function"
    assert payload[0]["function"]["name"] == "output"
    assert "title" not in payload[0]["function"]["parameters"]

    kwargs = client._build_request_kwargs(model="gpt-4o-mini", messages=[], tools_payload=payload)
    assert kwargs["stream"] is True
    assert kwargs["tool_choice"] == {"type": "function", "function": {"name": "output"}}


def test_anthropic_build_tools_payload_shape():
    anthropic = pytest.importorskip("anthropic")
    from eventloom.contrib.pydantic_v1.providers.anthropic import AnthropicStreamClient

    client = AnthropicStreamClient(client=anthropic.AsyncAnthropic(api_key="test-key"))
    payload = client._build_tools_payload(Widget)
    assert payload[0]["name"] == "output"
    assert "title" not in payload[0]["input_schema"]

    kwargs = client._build_request_kwargs(model="claude-haiku-4-5", messages=[], tools_payload=payload)
    assert kwargs["stream"] is True
    assert kwargs["max_tokens"] == 4096
    assert kwargs["tool_choice"] == {"type": "tool", "name": "output"}
