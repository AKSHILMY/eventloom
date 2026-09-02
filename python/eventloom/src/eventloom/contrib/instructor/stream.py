"""High-level streaming helpers: ``stream_model`` and ``stream_items``.

Both functions accept a ``provider_model`` string in the format
``"provider/model-name"`` understood by ``instructor.from_provider()``.
For example:

* ``"openai/gpt-4o-mini"``           (needs ``OPENAI_API_KEY``)
* ``"anthropic/claude-haiku-4-5-latest"``  (needs ``ANTHROPIC_API_KEY``)
* ``"google/gemini-1.5-flash"``      (needs ``GOOGLE_API_KEY``)

See https://python.useinstructor.com/integrations/ for the full list of
supported provider strings and their required environment variables.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Type, TypeVar

from eventloom.core import _compat
from eventloom.core.emitter import EventEmitter
from eventloom.core.model_emitter import ModelEmitter

if TYPE_CHECKING:
    pass

_V1_SCHEMA_MSG = (
    "eventloom.contrib.instructor does not support Pydantic v1 models — "
    "instructor itself requires Pydantic v2.\n\n"
    "For Pydantic v1 schemas use the dedicated helper instead:\n"
    "  from eventloom.contrib.pydantic_v1.providers.openai import stream_model\n"
    "  from eventloom.contrib.pydantic_v1.providers.anthropic import stream_model\n\n"
    "Or migrate your schema to Pydantic v2 (replace `from pydantic.v1 import` "
    "with `from pydantic import`)."
)

T = TypeVar("T")

_INSTRUCTOR_MISSING = (
    "eventloom.contrib.instructor requires the 'instructor' package.\n"
    "Install it with:  pip install \"eventloom[instructor]\""
)


def _get_async_client(provider_model: str, **client_kwargs: Any) -> Any:
    """Return an ``instructor.AsyncInstructor`` for *provider_model*.

    ``provider_model`` is the full ``"provider/model-name"`` string passed
    directly to ``instructor.from_provider()``.
    """
    try:
        import instructor  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(_INSTRUCTOR_MISSING) from exc
    return instructor.from_provider(provider_model, async_client=True, **client_kwargs)


async def stream_model(
    emitter: EventEmitter,
    prefix: str,
    schema: Type[T],
    *,
    provider_model: str,
    messages: list[dict[str, Any]],
    id: str | None = None,
    max_tokens: int = 1024,
    auto_register: bool = False,
    **llm_kwargs: Any,
) -> None:
    """Stream a Pydantic model field-by-field via instructor and auto-emit events.

    Uses ``instructor.AsyncInstructor.create_partial()`` which yields a
    progressively more-complete instance of *schema* on every token chunk.
    Each chunk is forwarded to a :class:`~eventloom.core.ModelEmitter` which
    computes the delta automatically and emits:

    * ``prefix`` (``strategy="merge"``) — for scalar / nested-model fields.
    * ``"{prefix}.{field}"`` (``strategy="append"``) — for each list field
      whose item type is a Pydantic model.

    Parameters
    ----------
    emitter:
        The :class:`~eventloom.core.EventEmitter` to emit events through.
    prefix:
        The event-type prefix registered (or to be registered) with
        :meth:`~eventloom.core.EventTypeRegistry.register_model`.
    schema:
        A Pydantic **v2** ``BaseModel`` subclass to stream.  Pydantic v1
        models are not supported by instructor; use
        ``eventloom.contrib.pydantic_v1.providers`` instead.
    provider_model:
        ``"provider/model-name"`` string understood by
        ``instructor.from_provider()``, e.g. ``"openai/gpt-4o-mini"`` or
        ``"anthropic/claude-haiku-4-5-latest"``.
    messages:
        Chat messages in OpenAI format (``[{"role": ..., "content": ...}]``).
    id:
        Envelope ``id`` for the merge event stream.  Defaults to *prefix*.
    max_tokens:
        Token budget forwarded to the LLM.  Required by some providers
        (e.g. Anthropic) even when not strictly necessary for others, so it
        is always passed.
    auto_register:
        If ``True`` and *prefix* is not yet registered in the emitter's
        registry, calls ``registry.register_model(prefix, schema)``
        automatically before streaming.  Defaults to ``False`` — explicit
        registration is recommended so the frontend mapping is clear.
    **llm_kwargs:
        Extra keyword arguments forwarded to ``instructor``'s
        ``create_partial()`` (e.g. ``temperature``, ``top_p``).

    Example::

        registry = EventTypeRegistry()
        registry.register_model("profile", UserProfile)
        ...
        await stream_model(
            emitter, "profile", UserProfile,
            provider_model="openai/gpt-4o-mini",
            messages=[{"role": "user", "content": "Generate a user profile for Alice."}],
            id="profile-1",
        )
    """
    if _compat.is_v1_style(schema):
        raise TypeError(_V1_SCHEMA_MSG)

    if auto_register and prefix not in emitter.registry:
        emitter.registry.register_model(prefix, schema)

    client = _get_async_client(provider_model)

    async with ModelEmitter(emitter, prefix, id=id) as me:
        stream = client.create_partial(
            response_model=schema,
            messages=messages,
            max_tokens=max_tokens,
            **llm_kwargs,
        )
        async for partial in stream:
            await me.emit_partial(partial)


async def stream_items(
    emitter: EventEmitter,
    event_type: str,
    schema: Type[T],
    *,
    provider_model: str,
    messages: list[dict[str, Any]],
    id: str | None = None,
    max_tokens: int = 1024,
    done: bool = True,
    **llm_kwargs: Any,
) -> int:
    """Stream multiple complete Pydantic model instances via instructor and auto-emit.

    Uses ``instructor.AsyncInstructor.create_iterable()`` which yields one
    *fully validated* instance of *schema* per completed object in the stream.
    Each item is emitted directly as an ``append`` event:

        ``await emitter.emit(event_type, item, id=id)``

    This mirrors what you'd write manually — the benefit here is the
    provider/model wiring and the boilerplate loop.

    Parameters
    ----------
    emitter:
        The :class:`~eventloom.core.EventEmitter` to emit events through.
    event_type:
        The registered event type name (``strategy="append"``).
    schema:
        A Pydantic **v2** ``BaseModel`` subclass for each item.  Pydantic v1
        models are not supported by instructor; use
        ``eventloom.contrib.pydantic_v1.providers`` instead.
    provider_model:
        ``"provider/model-name"`` string, e.g. ``"openai/gpt-4o-mini"``.
    messages:
        Chat messages in OpenAI format.
    id:
        Envelope ``id`` shared by all items in the stream.  Defaults to
        *event_type*.
    max_tokens:
        Token budget forwarded to the LLM.
    done:
        If ``True`` (default), emits a final ``done=True`` marker on *id*
        after all items have been streamed so the frontend can close the list.
    **llm_kwargs:
        Extra keyword arguments forwarded to ``instructor``'s
        ``create_iterable()``.

    Returns
    -------
    int
        The number of items emitted.

    Example::

        count = await stream_items(
            emitter, "company.insight", Insight,
            provider_model="anthropic/claude-haiku-4-5-latest",
            messages=[{"role": "user", "content": "Generate 3 investor insights."}],
            id="insights",
        )
    """
    if _compat.is_v1_style(schema):
        raise TypeError(_V1_SCHEMA_MSG)

    effective_id = id or event_type
    client = _get_async_client(provider_model)

    stream = client.create_iterable(
        response_model=schema,
        messages=messages,
        max_tokens=max_tokens,
        **llm_kwargs,
    )

    count = 0
    async for item in stream:
        await emitter.emit(event_type, item, id=effective_id)
        count += 1

    if done and count > 0:
        # Emit a done marker so the frontend knows the list is complete.
        # We use an empty dict validated against the schema; since the
        # event_type is registered with the schema, an empty dict that
        # matches Optional fields (or required ones via model_construct)
        # is used. We send done=True with the last item's schema.
        from eventloom.core import schema_utils as _su  # noqa: PLC0415
        spec = emitter.registry.get(event_type)
        empty = _su.make_delta_instance(spec.schema, {})
        await emitter.emit(event_type, empty, id=effective_id, done=True)

    return count
