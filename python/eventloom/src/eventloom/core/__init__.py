"""Framework-agnostic core: envelope model, event type registry, emitter.

Nothing in this subpackage imports FastAPI, Flask, or any web framework —
that's the whole point (see `eventloom-project-plan.md` section 1). Framework
integration lives in `eventloom.adapters.*`.
"""

from .emitter import EmitterClosedError, EventEmitter
from .envelope import STREAM_ERROR_TYPE, MergeStrategy, StreamEnvelope, StreamError
from .model_emitter import ModelEmitter
from .registry import (
    DuplicateEventTypeError,
    EventTypeRegistry,
    EventTypeSpec,
    UnknownEventTypeError,
)
from .serializers import JSONSerializer, Serializer, default_serializer

__all__ = [
    "STREAM_ERROR_TYPE",
    "DuplicateEventTypeError",
    "EmitterClosedError",
    "EventEmitter",
    "EventTypeRegistry",
    "EventTypeSpec",
    "JSONSerializer",
    "MergeStrategy",
    "ModelEmitter",
    "Serializer",
    "StreamEnvelope",
    "StreamError",
    "UnknownEventTypeError",
    "default_serializer",
]
