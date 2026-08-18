"""FastAPI `Depends()` integration: build a per-request `EventEmitter` bound
to a shared registry, optionally deriving `group_id` from the request (e.g.
from an auth-context user id or a path parameter).
"""

from __future__ import annotations

from typing import Callable

from fastapi import Request

from ...core.emitter import EventEmitter
from ...core.registry import EventTypeRegistry

GroupIdResolver = Callable[[Request], "str | None"]


def emitter_dependency(
    registry: EventTypeRegistry,
    group_id_from: GroupIdResolver | None = None,
) -> Callable[[Request], EventEmitter]:
    """Build a FastAPI dependency that yields a fresh `EventEmitter` per request.

        from eventloom.adapters.fastapi import emitter_dependency, to_sse_response
        from myapp.events import registry

        get_emitter = emitter_dependency(registry)

        @app.get("/stream/dashboard")
        async def dashboard_stream(emitter: EventEmitter = Depends(get_emitter)):
            return to_sse_response(emitter, run=lambda: run_dashboard_logic(emitter), request=request)

    Pass `group_id_from` to tag the emitter with a group id derived from the
    request (e.g. `lambda req: req.path_params["user_id"]`) — useful for
    logging/metrics correlation; it is not required by `EventEmitter` itself.
    """

    def _dependency(request: Request) -> EventEmitter:
        group_id = group_id_from(request) if group_id_from is not None else None
        return EventEmitter(registry, group_id=group_id)

    return _dependency
