from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Callable

from fastapi.routing import APIRoute, get_body_field, get_dependant, get_parameterless_sub_dependant, request_response


def patch_api_route(app: Any, path: str, methods: Iterable[str], endpoint: Callable[..., Any]) -> bool:
    expected_methods = {str(method).upper() for method in methods}
    for route in getattr(app, "routes", []):
        if not isinstance(route, APIRoute):
            continue
        if route.path != path:
            continue
        if route.methods != expected_methods:
            continue
        route.endpoint = endpoint
        route.dependant = get_dependant(path=route.path_format, call=route.endpoint)
        for depends in route.dependencies[::-1]:
            route.dependant.dependencies.insert(
                0,
                get_parameterless_sub_dependant(depends=depends, path=route.path_format),
            )
        route.body_field = get_body_field(dependant=route.dependant, name=route.unique_id)
        route.app = request_response(route.get_route_handler())
        return True
    return False
