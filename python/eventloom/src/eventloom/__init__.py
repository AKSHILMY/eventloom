"""eventloom — a generalized backend-to-frontend event streaming toolkit.

Framework-agnostic core (`eventloom.core`) plus opt-in framework adapters
(`eventloom.adapters.*`, e.g. `eventloom.adapters.fastapi`). See the package
README for a quickstart and the wire protocol reference.

The top-level namespace re-exports the core API — this is the entry point
most application code should import from:

    from eventloom import EventTypeRegistry, EventEmitter, StreamEnvelope
"""

from .core import (
    STREAM_ERROR_TYPE,
    DuplicateEventTypeError,
    EmitterClosedError,
    EventEmitter,
    EventTypeRegistry,
    EventTypeSpec,
    JSONSerializer,
    MergeStrategy,
    Serializer,
    StreamEnvelope,
    StreamError,
    UnknownEventTypeError,
    default_serializer,
)

__version__ = "0.1.0"

__all__ = [
    "STREAM_ERROR_TYPE",
    "DuplicateEventTypeError",
    "EmitterClosedError",
    "EventEmitter",
    "EventTypeRegistry",
    "EventTypeSpec",
    "JSONSerializer",
    "MergeStrategy",
    "Serializer",
    "StreamEnvelope",
    "StreamError",
    "UnknownEventTypeError",
    "default_serializer",
    "__version__",
]
