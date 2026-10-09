"""Rebuilt assets remain available without widening the static file boundary."""

from pathlib import Path

from django.http import Http404
from django.test import RequestFactory
import pytest

from relay.web import static_view
from tests.support import symlink_or_skip


def test_rebuilt_assets_are_served_without_restarting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    index = root / "index.html"
    index.write_text("old index", encoding="utf-8")
    old = root / "assets" / "old.js"
    old.write_text("old asset", encoding="utf-8")
    monkeypatch.setattr(static_view, "STATIC_ROOT", root)
    monkeypatch.setattr(static_view, "_STATIC_ASSETS", static_view._asset_catalog())
    old.unlink()
    current = root / "assets" / "current.js"
    current.write_text("current asset", encoding="utf-8")
    index.write_text("current index", encoding="utf-8")
    request = RequestFactory().get("/")
    response = static_view.serve_spa(request, "assets/current.js")
    try:
        assert b"".join(response.streaming_content) == b"current asset"
        assert "immutable" in response["Cache-Control"]
    finally:
        response.close()
    response = static_view.serve_spa(request)
    try:
        assert b"".join(response.streaming_content) == b"current index"
        assert response["Cache-Control"] == "no-cache"
    finally:
        response.close()
    with pytest.raises(Http404):
        static_view.serve_spa(request, "assets/old.js")
    outside = tmp_path / "private.js"
    outside.write_text("private", encoding="utf-8")
    current.unlink()
    symlink_or_skip(current, outside)
    with pytest.raises(Http404):
        static_view.serve_spa(request, "assets/current.js")
    with pytest.raises(Http404):
        static_view.serve_spa(request, "assets/../../private.js")


def test_static_compression_keeps_type_cache_and_encoding_negotiation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import gzip

    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    payload = b"console.log('static fixture');" * 100
    (root / "assets/main.js").write_bytes(payload)
    (root / "assets/main.js.gz").write_bytes(gzip.compress(payload))
    monkeypatch.setattr(static_view, "STATIC_ROOT", root)
    monkeypatch.setattr(static_view, "_STATIC_ASSETS", static_view._asset_catalog())
    request = RequestFactory().get("/assets/main.js", HTTP_ACCEPT_ENCODING="br, gzip")
    response = static_view.serve_spa(request, "assets/main.js")
    try:
        assert response["Content-Encoding"] == "gzip"
        assert response["Vary"] == "Accept-Encoding"
        assert "javascript" in response["Content-Type"]
        assert gzip.decompress(b"".join(response.streaming_content)) == payload
    finally:
        response.close()
    request = RequestFactory().get("/assets/main.js", HTTP_ACCEPT_ENCODING="gzip;q=0, br;q=0")
    response = static_view.serve_spa(request, "assets/main.js")
    try:
        assert "Content-Encoding" not in response
        assert b"".join(response.streaming_content) == payload
    finally:
        response.close()
