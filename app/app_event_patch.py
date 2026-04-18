from __future__ import annotations

from collections.abc import Callable
from typing import Any


def patch_app_event_handler(app: Any, phase: str, handler_name: str, new_handler: Callable[..., Any]) -> bool:
    router = getattr(app, "router", None)
    if router is None:
        return False
    if phase == "startup":
        handlers = getattr(router, "on_startup", None)
    elif phase == "shutdown":
        handlers = getattr(router, "on_shutdown", None)
    else:
        return False
    if not isinstance(handlers, list):
        return False
    for index, current in enumerate(handlers):
        if getattr(current, "__name__", None) != handler_name:
            continue
        handlers[index] = new_handler
        return True
    return False
