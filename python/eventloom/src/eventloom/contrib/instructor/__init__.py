"""
eventloom.contrib.instructor — High-level streaming helpers backed by ``instructor``.

Provides two functions that bridge ``instructor``'s structured-output streaming
directly into eventloom's event pipeline, so a developer only needs to specify
a schema, a provider/model string, and a prompt:

``stream_model``
    Partial field-by-field streaming of a single Pydantic model (wraps
    ``instructor.AsyncInstructor.create_partial`` + ``ModelEmitter``).
    Best for objects that build up gradually, e.g. a company profile.

``stream_items``
    Streaming of multiple complete Pydantic model instances (wraps
    ``instructor.AsyncInstructor.create_iterable`` + direct ``emitter.emit``).
    Best for growing lists of finished items, e.g. analyst insights.

Requires the ``instructor`` extra::

    pip install "eventloom[instructor]"

Usage::

    from eventloom.contrib.instructor import stream_model, stream_items

    # stream one object field-by-field
    await stream_model(
        emitter, "company.profile", CompanyProfile,
        provider_model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": "..."}],
        id="profile-1",
    )

    # stream a list of complete objects
    await stream_items(
        emitter, "company.insight", Insight,
        provider_model="anthropic/claude-haiku-4-5-latest",
        messages=[{"role": "user", "content": "..."}],
        id="insights",
    )
"""

from .stream import stream_items, stream_model

__all__ = ["stream_model", "stream_items"]
