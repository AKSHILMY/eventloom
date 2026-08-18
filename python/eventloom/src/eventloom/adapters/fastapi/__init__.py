"""FastAPI adapter — the first-class framework integration for eventloom.

Requires the `fastapi` extra: `pip install eventloom[fastapi]`.
"""

from .dependency import emitter_dependency
from .stream import to_sse_response

__all__ = ["emitter_dependency", "to_sse_response"]
