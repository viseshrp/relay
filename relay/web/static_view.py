"""Path-safe production serving for the packaged single-page application."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from django.http import FileResponse, Http404, HttpRequest
from django.views.decorators.http import require_http_methods

STATIC_ROOT = Path(__file__).resolve().parents[1] / "static"


def _asset_catalog() -> dict[str, Path]:
    """Index only packaged files that remain inside the resolved static root."""
    root = STATIC_ROOT.resolve()
    catalog: dict[str, Path] = {}
    for candidate in root.rglob("*"):
        try:
            resolved = candidate.resolve()
            relative = resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            continue
        if resolved.is_file():
            catalog[relative.as_posix()] = resolved
    return catalog


_STATIC_ASSETS = _asset_catalog()


def _asset(path: str) -> Path | None:
    return _STATIC_ASSETS.get(path)


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
