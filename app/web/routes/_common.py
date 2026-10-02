"""Small helpers the route modules share."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import RedirectResponse, Response


def is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def done(request: Request, to: str) -> Response:
    """After an action: HTMX loads `to` as a page; a plain form post gets a 303."""
    if is_htmx(request):
        return Response(status_code=200, headers={"HX-Redirect": to})
    return RedirectResponse(to, status_code=303)


async def form_values(request: Request) -> dict[str, Any]:
    """The posted form as text; a field sent more than once becomes a list."""
    form = await request.form()
    out: dict[str, Any] = {}
    for key in form.keys():
        if key == "csrf_token":
            continue
        values = [v for v in form.getlist(key) if isinstance(v, str)]
        out[key] = values if len(values) > 1 else (values[0] if values else "")
    return out


def int_or_none(text: Any) -> int | None:
    try:
        return int(str(text))
    except (TypeError, ValueError):
        return None
