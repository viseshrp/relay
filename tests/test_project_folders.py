"""Folder browsing follows symlinks before checking the owner-home boundary."""

from pathlib import Path

from django.test import Client
import pytest

from relay.errors import ConfigError, PathSafetyError
from relay.projects import folders
from tests.support import symlink_or_skip
from tests.test_web_api import client as client
from tests.test_web_api import owner as owner


def test_directory_listing_is_sorted_paged_and_contains_no_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner: Client
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(folders, "_home_directory", lambda: home)
    for name in ["zeta", "Alpha", "beta"]:
        (home / name).mkdir()
    (home / "Alpha" / ".git").mkdir()
    (home / "private.txt").write_text("Never return these bytes", encoding="utf-8")
    first = owner.get("/api/projects/folders?limit=2")
    assert first.status_code == 200
    payload = first.json()
    assert payload["root"] == payload["path"] == str(home)
    assert payload["parent"] is None
    assert payload["next"] == "beta"
    assert payload["folders"] == [
        {"name": "Alpha", "path": str(home / "Alpha"), "repository": True},
        {"name": "beta", "path": str(home / "beta"), "repository": False},
    ]
    second = owner.get("/api/projects/folders?since=beta&limit=2").json()
    assert [entry["name"] for entry in second["folders"]] == ["zeta"]
    assert second["next"] is None
    child = owner.get("/api/projects/folders", {"path": str(home / "beta")}).json()
    assert child["parent"] == str(home)
    assert child["folders"] == []
    assert Client().get("/api/projects/folders").status_code == 401
    assert owner.get("/api/projects/folders?limit=0").status_code == 400
    assert owner.get("/api/projects/folders?path=missing").status_code == 400
    assert owner.get("/api/projects/folders", {"path": str(tmp_path)}).status_code == 400


def test_folder_symlinks_cannot_escape_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "inside").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(folders, "_home_directory", lambda: home)
    symlink_or_skip(home / "escape", outside)
    symlink_or_skip(home / "alias", home / "inside")
    listing = folders.browse_folders()
    assert [entry.name for entry in listing.folders] == ["alias", "inside"]
    assert listing.folders[0].path == str(home / "inside")
    with pytest.raises(PathSafetyError):
        folders.browse_folders(str(home / "escape"))
    with pytest.raises(PathSafetyError):
        folders.browse_folders("../outside")


def test_unreadable_folders_return_a_relay_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(folders, "_home_directory", lambda: tmp_path)

    def denied(_path: Path) -> None:
        raise PermissionError

    monkeypatch.setattr(Path, "iterdir", denied)
    with pytest.raises(ConfigError, match="cannot list"):
        folders.browse_folders()
    with pytest.raises(ConfigError, match="too long"):
        folders.browse_folders("x" * 4097)
    with pytest.raises(ConfigError, match="too long"):
        folders.browse_folders(since="x" * 1025)
