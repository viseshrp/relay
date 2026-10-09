"""Path-safe production serving for the packaged single-page application."""

from __future__ import annotations

from pathlib import Path

from django.http import FileResponse, Http404, HttpRequest
from django.views.decorators.http import require_http_methods

from relay.media import media_type_for

STATIC_ROOT = Path(__file__).resolve().parents[1] / "static"


def _asset_catalog() -> dict[str, Path]:
    """Index only packaged files that remain inside the resolved static root."""
    root = STATIC_ROOT.resolve()
    catalog = {}
    for candidate in root.rglob("*"):
        try:
            resolved = candidate.resolve()
            relative = resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            continue
        if resolved.is_file():
            catalog[relative.as_posix()] = resolved
    return catalog


_STATIC_ASSETS: dict[str, Path] = _asset_catalog()


def _asset(path: str) -> Path | None:
    if path.startswith(".") or "/." in path or path.endswith(".map"):
        return None
    candidate = _STATIC_ASSETS.get(path)
    if candidate is None or not candidate.is_file():
        # Editable checkouts can replace their hashed assets while the server runs.
        _STATIC_ASSETS.clear()
        _STATIC_ASSETS.update(_asset_catalog())
        candidate = _STATIC_ASSETS.get(path)
    if candidate is None:
        return None
    try:
        resolved = candidate.resolve()
        resolved.relative_to(STATIC_ROOT.resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved if resolved.is_file() else None


@require_http_methods(("GET", "HEAD"))
def serve_spa(request: HttpRequest, asset_path: str = "") -> FileResponse:
    """Serve immutable build assets or fall back to `index.html` for app routes."""
    requested = _asset(asset_path) if asset_path else None
    if asset_path.startswith("assets/") and requested is None:
        raise Http404
    path = requested or _asset("index.html")
    if path is None:
        raise Http404
    original = path
    encodings: list[tuple[float, int, str]] = []
    for part in request.headers.get("Accept-Encoding", "").split(","):
        values = part.strip().split(";")
        encoding = values[0].strip()
        if encoding not in {"br", "gzip"}:
            continue
        try:
            quality = float(
                next(
                    (value.strip()[2:] for value in values[1:] if value.strip().startswith("q=")),
                    "1",
                )
            )
        except ValueError:
            continue
        if 0 < quality <= 1:
            encodings.append((quality, int(encoding == "br"), encoding))
    content_encoding = None
    for _quality, _priority, encoding in sorted(encodings, reverse=True):
        relative = original.relative_to(STATIC_ROOT.resolve()).as_posix()
        compressed = _asset(relative + (".br" if encoding == "br" else ".gz"))
        if compressed is not None:
            path, content_encoding = compressed, encoding
            break
    try:
        asset = path.open("rb")
    except OSError:
        raise Http404 from None
    response = FileResponse(asset, content_type=media_type_for(original))
    response["Vary"] = "Accept-Encoding"
    if content_encoding is not None:
        response["Content-Encoding"] = content_encoding
    response["Cache-Control"] = (
        "public, max-age=31536000, immutable"
        if requested is not None and asset_path.startswith("assets/")
        else "no-cache"
    )
    return response


__all__ = ["STATIC_ROOT", "serve_spa"]
