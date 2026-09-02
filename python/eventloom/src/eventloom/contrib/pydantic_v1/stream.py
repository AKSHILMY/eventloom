"""High-level streaming helpers for Pydantic v1 models.

Mirrors ``eventloom.contrib.instructor.stream_model`` / ``stream_items`` for
the Pydantic v2 + instructor path, but for Pydantic v1 schemas via the
``eventloom.contrib.pydantic_v1.providers`` clients.

Why a separate module?
  ``instructor`` does not support Pydantic v1 models.  The ``contrib.pydantic_v1``
  module fills that gap with its own partial-JSON-streaming approach
  (``ProviderStreamClient.stream()``).  These helpers wire that streaming
  directly into :class:`~eventloom.core.ModelEmitter`, eliminating the manual
  ``sent`` dict / diff / ``done=True`` boilerplate that the original
  ``dashboard_app_pydantic_v1.py`` example shows.

Usage::

    from eventloom.contrib.pydantic_v1 import BaseModel, stream_model, stream_items
    from eventloom.contrib.pydantic_v1.providers.openai import OpenAIStreamClient

    class Profile(BaseModel):
        name: Optional[str] = None
        bio: Optional[str] = None

    client = OpenAIStreamClient()
    registry.register_model("profile", Profile)

    await stream_model(
        emitter, "profile", Profile,
        client=client,
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Generate a profile for Alice."}],
        id="p-1",
    )
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, List, Optional, Type, TypeVar

from eventloom.core import _compat
from eventloom.core.emitter import EventEmitter
from eventloom.core.model_emitter import ModelEmitter
from eventloom.core import schema_utils as _su

from .streaming import stream_new_list_items

if TYPE_CHECKING:
    from .providers.base import ProviderStreamClient

T = TypeVar("T")

_V2_SCHEMA_MSG = (
    "eventloom.contrib.pydantic_v1.stream_model/stream_items only accept Pydantic v1 "
    "models (from pydantic.v1 import BaseModel).\n\n"
    "For Pydantic v2 schemas use the instructor-based helper instead:\n"
    "  from eventloom.contrib.instructor import stream_model, stream_items"
)


async def stream_model(
    emitter: EventEmitter,
    prefix: str,
    schema: Type[T],
    *,
    client: "ProviderStreamClient",
    model: str,
    messages: List[Any],
    id: Optional[str] = None,
    auto_register: bool = False,
    **provider_kwargs: Any,
) -> None:
    """Stream a Pydantic v1 model field-by-field and auto-emit events.

    Wraps ``client.stream()`` with a :class:`~eventloom.core.ModelEmitter`,
    providing the same high-level experience as
    ``eventloom.contrib.instructor.stream_model`` but for Pydantic v1 schemas.

    The :class:`~eventloom.core.ModelEmitter` handles all of:

    * Delta tracking — only changed scalar fields are emitted each chunk.
    * List-of-model watermarking — new items in ``list[SubModel]`` fields are
      routed to their own ``"{prefix}.{field_name}"`` append events.
    * ``done=True`` signal — automatically sent on context-manager exit.

    Parameters
    ----------
    emitter:
        The :class:`~eventloom.core.EventEmitter` to emit events through.
    prefix:
        The event-type prefix registered (or to be registered) with
        :meth:`~eventloom.core.EventTypeRegistry.register_model`.
    schema:
        A Pydantic **v1** ``BaseModel`` subclass (``from pydantic.v1 import
        BaseModel`` or ``from eventloom.contrib.pydantic_v1 import BaseModel``).
        Pydantic v2 models are not accepted here — use
        ``eventloom.contrib.instructor.stream_model`` instead.
    client:
        A :class:`~eventloom.contrib.pydantic_v1.providers.base.ProviderStreamClient`
        instance (e.g. ``OpenAIStreamClient()``, ``AnthropicStreamClient()``).
    model:
        The LLM model identifier string passed to ``client.stream()``,
        e.g. ``"gpt-4o-mini"`` or ``"claude-haiku-4-5-latest"``.
    messages:
        Chat messages in OpenAI format (``[{"role": ..., "content": ...}]``).
    id:
        Envelope ``id`` for the merge event stream.  Defaults to *prefix*.
    auto_register:
        If ``True`` and *prefix* is not yet registered in the emitter's
        registry, calls ``registry.register_model(prefix, schema)``
        automatically before streaming.  Defaults to ``False`` — explicit
        registration is recommended so the event-type map is clear.
    **provider_kwargs:
        Extra keyword arguments forwarded to ``client.stream()``
        (e.g. ``temperature``, ``max_tokens``).

    Example::

        from eventloom.contrib.pydantic_v1 import BaseModel, stream_model
        from eventloom.contrib.pydantic_v1.providers.openai import OpenAIStreamClient
        from typing import Optional, List

        class KeyProduct(BaseModel):
            name: str
            tagline: Optional[str] = None

        class CompanyProfile(BaseModel):
            name: Optional[str] = None
            key_products: List[KeyProduct] = []

        client = OpenAIStreamClient()
        registry.register_model("company.profile", CompanyProfile)

        await stream_model(
            emitter, "company.profile", CompanyProfile,
            client=client,
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Profile Nimbus Systems."}],
            id="profile-1",
        )
    """
    if not _compat.is_v1_style(schema):
        raise TypeError(_V2_SCHEMA_MSG)

    if auto_register and prefix not in emitter.registry:
        emitter.registry.register_model(prefix, schema)

    async with ModelEmitter(emitter, prefix, id=id, model_cls=schema) as me:
        async for partial in client.stream(
            model=model,
            response_model=schema,
            messages=messages,
            **provider_kwargs,
        ):
            await me.emit_partial(partial)


async def stream_items(
    emitter: EventEmitter,
    event_type: str,
    schema: Type[T],
    *,
    client: "ProviderStreamClient",
    model: str,
    messages: List[Any],
    get_list: Callable[[Any], List[Any]],
    wrapper_schema: Type[Any],
    id: Optional[str] = None,
    is_complete: Optional[Callable[[Any], bool]] = None,
    done: bool = True,
    **provider_kwargs: Any,
) -> int:
    """Stream multiple complete Pydantic v1 model instances and auto-emit append events.

    Pydantic v1 has no ``create_iterable()`` equivalent, so the standard
    approach is to wrap the target items in a batch model with a list field and
    use :func:`~eventloom.contrib.pydantic_v1.streaming.stream_new_list_items`
    to extract completed items as the stream progresses.  This helper does that
    wiring for you.

    Parameters
    ----------
    emitter:
        The :class:`~eventloom.core.EventEmitter` to emit events through.
    event_type:
        The registered event type name (``strategy="append"``).
    schema:
        A Pydantic **v1** ``BaseModel`` subclass for each individual item.
    client:
        A :class:`~eventloom.contrib.pydantic_v1.providers.base.ProviderStreamClient`
        instance.
    model:
        The LLM model identifier string.
    messages:
        Chat messages in OpenAI format.
    get_list:
        Callable that extracts the growing list of items from each partial
        batch object, e.g. ``lambda p: p.insights``.
    wrapper_schema:
        A Pydantic v1 ``BaseModel`` subclass that wraps the items in a list
        field.  ``client.stream()`` is called with this as ``response_model``.
        Example::

            class InsightsBatch(BaseModel):
                insights: List[Insight] = []

    id:
        Envelope ``id`` shared by all items in the stream.  Defaults to
        *event_type*.
    is_complete:
        Optional predicate that returns ``True`` when an item extracted from
        the partial stream is complete enough to emit.  Defaults to
        ``stream_new_list_items``'s built-in heuristic (all required fields
        are non-None).
    done:
        If ``True`` (default), emits a final ``done=True`` marker after all
        items have been streamed.
    **provider_kwargs:
        Extra keyword arguments forwarded to ``client.stream()``.

    Returns
    -------
    int
        The number of items emitted.

    Example::

        class Insight(BaseModel):
            title: str
            detail: str
            signal: str

        class InsightsBatch(BaseModel):
            insights: List[Insight] = []

        count = await stream_items(
            emitter, "company.insight", Insight,
            client=client,
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Generate 3 insights."}],
            wrapper_schema=InsightsBatch,
            get_list=lambda p: p.insights,
            id="insights",
        )
    """
    if not _compat.is_v1_style(schema):
        raise TypeError(_V2_SCHEMA_MSG)

    effective_id = id or event_type
    partial_stream = client.stream(
        model=model,
        response_model=wrapper_schema,
        messages=messages,
        **provider_kwargs,
    )

    kwargs: dict[str, Any] = {"get_list": get_list}
    if is_complete is not None:
        kwargs["is_complete"] = is_complete

    count = 0
    async for item in stream_new_list_items(partial_stream, **kwargs):
        await emitter.emit(event_type, item, id=effective_id)
        count += 1

    if done and count > 0:
        spec = emitter.registry.get(event_type)
        empty = _su.make_delta_instance(spec.schema, {})
        await emitter.emit(event_type, empty, id=effective_id, done=True)

    return count
