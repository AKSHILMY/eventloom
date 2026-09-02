"""
Abstract base for LLM provider stream clients.

All providers implement:
    _build_tools_payload(model_cls) -> provider-specific tool definition
    _build_request_kwargs(model, messages, tools_payload, **kwargs) -> dict
    _raw_token_stream(**request_kwargs) -> AsyncGenerator[str, None]

The base class stream() method owns: JSON accumulation, partial repair,
partial model construction, and a final validation pass. Adding a new
provider means only subclassing this.
"""

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Type, TypeVar

from .._pydantic1 import BaseModel, ValidationError
from ..errors import PartialStreamValidationError
from ..json_parser import parse_partial_json
from ..partial import build_partial_model

M = TypeVar("M", bound=BaseModel)


class ProviderStreamClient(ABC):

    @abstractmethod
    def _build_tools_payload(self, model_cls: Type[BaseModel]) -> Any:
        """Return the provider-specific tool/function definition from model_cls.schema()."""
        ...

    @abstractmethod
    def _build_request_kwargs(
        self,
        model: str,
        messages: List[Dict[str, str]],
        tools_payload: Any,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Return keyword arguments for the provider's create() call."""
        ...

    @abstractmethod
    async def _raw_token_stream(self, **request_kwargs: Any) -> AsyncGenerator[str, None]:
        """
        Async generator yielding raw JSON string fragments (deltas) from the
        LLM stream, one per chunk. Empty strings should be skipped.
        """
        ...

    async def stream(
        self,
        model: str,
        response_model: Type[M],
        messages: List[Dict[str, str]],
        *,
        validate_final: bool = True,
        **kwargs: Any,
    ) -> AsyncGenerator[M, None]:
        """
        Stream partial model instances.

        Accumulates raw JSON tokens, repairs partial JSON on each token, and
        yields a new partial model instance whenever parsing succeeds. Every
        one of these intermediate yields is cheap and best-effort — built via
        `Model.construct()`, which never validates and never fails on
        missing/malformed fields, exactly as before this method gained a
        final-validation pass.

        Once the underlying token stream ends, one *additional* yield is
        appended (unless `validate_final=False`): a real, validated instance
        built via `response_model.parse_obj()` on the fully accumulated data.
        This is what lets a caller trust "the last thing `.stream()` yielded"
        the way they'd trust `instructor`'s validated output — previously
        that last item was still just an unvalidated `.construct()` result
        like every other partial.

        Args:
            model: The LLM model identifier string.
            response_model: A Pydantic v1 BaseModel subclass.
            messages: Messages list in OpenAI format.
            validate_final: If True (default), append one final, genuinely
                validated instance once the stream ends; raises
                `PartialStreamValidationError` if the accumulated stream
                still isn't parseable JSON or doesn't satisfy
                `response_model`. Pass False to keep the original behavior
                (stream ends after the last best-effort partial, no
                validation, never raises on the model's account).
            **kwargs: Extra provider-specific kwargs (temperature, max_tokens…).

        Yields:
            Partial instances of response_model, progressively more
            complete, then (if `validate_final`) one final validated
            instance.
        """
        tools_payload = self._build_tools_payload(response_model)
        request_kwargs = self._build_request_kwargs(
            model=model,
            messages=messages,
            tools_payload=tools_payload,
            **kwargs,
        )

        accumulated = ""
        async for token in self._raw_token_stream(**request_kwargs):
            accumulated += token
            parsed = parse_partial_json(accumulated)
            if parsed is not None:
                yield build_partial_model(response_model, parsed)

        if not validate_final:
            return

        final_parsed = parse_partial_json(accumulated)
        if final_parsed is None:
            raise PartialStreamValidationError(
                f"{response_model.__name__}: stream ended with no parseable JSON "
                f"({len(accumulated)} chars accumulated)."
            )
        try:
            yield response_model.parse_obj(final_parsed)
        except ValidationError as exc:
            raise PartialStreamValidationError(
                f"{response_model.__name__}: final object failed validation. "
                f"Errors: {exc.errors()}"
            ) from exc

    async def create(
        self,
        model: str,
        response_model: Type[M],
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> M:
        """Non-streaming convenience: mirrors `instructor`'s plain `.create()`
        — returns a single, fully-validated object, no partial yielding in
        the caller-facing API.

        Internally reuses `.stream(..., validate_final=True)` end-to-end
        rather than duplicating the request/parse/validate logic in a
        separate code path, so `.stream()` stays the single source of truth
        for validation. The trade-off is this still issues a streamed
        request under the hood even though only the final object is
        returned — deliberate, for that reason.
        """
        result = None
        async for item in self.stream(
            model=model,
            response_model=response_model,
            messages=messages,
            validate_final=True,
            **kwargs,
        ):
            result = item
        if result is None:
            raise PartialStreamValidationError(f"{response_model.__name__}: no data received.")
        return result
