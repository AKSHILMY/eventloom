"""
OpenAI streaming provider for eventloom.contrib.pydantic_v1.

Uses tool calling (function calling) to force structured JSON output.
The model fills in the schema defined by Model.schema() (Pydantic v1).

Token extraction path:
    chunk.choices[0].delta.tool_calls[0].function.arguments
"""

import logging
from typing import Any, AsyncGenerator, Dict, List, Optional, Type

from openai import AsyncOpenAI

from .._pydantic1 import BaseModel
from .base import ProviderStreamClient

logger = logging.getLogger("eventloom.contrib.pydantic_v1")


class OpenAIStreamClient(ProviderStreamClient):
    """
    Pydantic v1 partial streaming client backed by AsyncOpenAI.

    Args:
        client: An AsyncOpenAI instance. If None, one is created with no
                arguments — `AsyncOpenAI()` reads `OPENAI_API_KEY` from the
                environment itself, so no bespoke credentials plumbing is
                needed here.
        tool_name: Name used for the synthetic tool. Defaults to "output".
    """

    def __init__(self, client: Optional[AsyncOpenAI] = None, tool_name: str = "output") -> None:
        self._client = client if client is not None else AsyncOpenAI()
        self._tool_name = tool_name

    def _build_tools_payload(self, model_cls: Type[BaseModel]) -> List[Dict[str, Any]]:
        schema = model_cls.schema()
        schema.pop("title", None)
        return [
            {
                "type": "function",
                "function": {
                    "name": self._tool_name,
                    "description": f"Extract structured data matching the {model_cls.__name__} schema.",
                    "parameters": schema,
                },
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
            "tool_choice": {"type": "function", "function": {"name": self._tool_name}},
            "stream": True,
            **kwargs,
        }

    async def _raw_token_stream(self, **request_kwargs: Any) -> AsyncGenerator[str, None]:
        response = await self._client.chat.completions.create(**request_kwargs)
        async for chunk in response:
            try:
                tool_calls = chunk.choices[0].delta.tool_calls
                if tool_calls:
                    args = tool_calls[0].function.arguments
                    if args:
                        yield args
            except (AttributeError, IndexError) as exc:
                # Expected/frequent — e.g. the final finish-reason chunk has
                # no tool_calls at all. Not logged above debug: this is
                # routine per-chunk shape variation, not an anomaly.
                logger.debug("Skipping malformed OpenAI stream chunk: %r", exc)
                continue
