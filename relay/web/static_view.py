"""Path-safe production serving for the packaged single-page application."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from django.http import FileResponse, Http404, HttpRequest
from django.views.decorators.http import require_http_methods

from relay.errors import PathSafetyError
from relay.paths import safe_resolve

STATIC_ROOT = Path(__file__).resolve().parents[1] / "static"


def _asset(path: str) -> Path | None:
    try:
        candidate = safe_resolve(STATIC_ROOT, path)
    except PathSafetyError:
        return None
    return candidate if candidate.is_file() else None


@require_http_methods(("GET", "HEAD"))
def serve_spa(request: HttpRequest, asset_path: str = "") -> FileResponse:
    """Serve immutable build assets or fall back to `index.html` for app routes."""
    del request
    requested = _asset(asset_path) if asset_path else None
    if asset_path.startswith("assets/") and requested is None:
        raise Http404
    path = requested or _asset("index.html")
    if path is None:
        raise Http404
    media_type, _encoding = mimetypes.guess_type(path.name)
    response = FileResponse(path.open("rb"), content_type=media_type or "application/octet-stream")
    response["Cache-Control"] = (
        "public, max-age=31536000, immutable"
        if requested is not None and asset_path.startswith("assets/")
        else "no-cache"
    )
    return response


__all__ = ["STATIC_ROOT", "serve_spa"]
