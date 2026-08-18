"""
Anthropic streaming provider for eventloom.contrib.pydantic_v1.

Uses tool_use to force structured JSON output.
The model fills in the schema defined by Model.schema() (Pydantic v1).

Token extraction path:
    event.type == "content_block_delta"
    AND event.delta.type == "input_json_delta"
    -> event.delta.partial_json
"""

import logging
from typing import Any, AsyncGenerator, Dict, List, Optional, Type

from anthropic import AsyncAnthropic

from .._pydantic1 import BaseModel
from .base import ProviderStreamClient

logger = logging.getLogger("eventloom.contrib.pydantic_v1")

_DEFAULT_MAX_TOKENS = 4096


class AnthropicStreamClient(ProviderStreamClient):
    """
    Pydantic v1 partial streaming client backed by AsyncAnthropic.

    Args:
        client: An AsyncAnthropic instance. If None, one is created with no
                arguments — `AsyncAnthropic()` reads `ANTHROPIC_API_KEY` from
                the environment itself, so no bespoke credentials plumbing is
                needed here.
        tool_name: Name used for the synthetic tool. Defaults to "output".
        max_tokens: Max tokens for the Anthropic call (required by API). Defaults to 4096.
    """

    def __init__(
        self,
        client: Optional[AsyncAnthropic] = None,
        tool_name: str = "output",
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        self._client = client if client is not None else AsyncAnthropic()
        self._tool_name = tool_name
        self._max_tokens = max_tokens

    def _build_tools_payload(self, model_cls: Type[BaseModel]) -> List[Dict[str, Any]]:
        schema = model_cls.schema()
        schema.pop("title", None)
        return [
            {
                "name": self._tool_name,
                "description": f"Extract structured data matching the {model_cls.__name__} schema.",
                "input_schema": schema,
            }
        ]

    def _build_request_kwargs(
        self,
        model: str,
        messages: List[Dict[str, str]],
        tools_payload: Any,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return {
            "model": model,
            "messages": messages,
            "tools": tools_payload,
            "tool_choice": {"type": "tool", "name": self._tool_name},
            "max_tokens": self._max_tokens,
            "stream": True,
            **kwargs,
        }

    async def _raw_token_stream(self, **request_kwargs: Any) -> AsyncGenerator[str, None]:
        response = await self._client.messages.create(**request_kwargs)
        async for event in response:
            try:
                if event.type == "content_block_delta" and event.delta.type == "input_json_delta":
                    if event.delta.partial_json:
                        yield event.delta.partial_json
            except AttributeError as exc:
                # Expected/frequent — many event types (message_start,
                # content_block_start, message_delta, ...) don't carry a
                # `.delta.type`/`.delta.partial_json` at all.
                logger.debug("Skipping malformed Anthropic stream event: %r", exc)
                continue
