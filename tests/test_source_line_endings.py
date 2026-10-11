"""Editor hashes and immutable snapshots agree on the exact source bytes."""

from __future__ import annotations

from hashlib import sha256

from django.test import Client
import pytest

from relay.workflows.editor import read_prompt_document, save_prompt_document
from relay.workflows.loader import load_workflow
from relay.workflows.snapshot import build_snapshot
from relay.workflows.validation import validate_loaded_workflow
from tests.support import RelayProject
from tests.test_editor_recovery import SOURCE, owner, post

__all__ = ["owner"]


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_workflow_round_trip_and_draft_conflicts_use_exact_bytes(
    owner: Client, project: RelayProject, newline: str
) -> None:
    source = project.relay_root / "workflows/check.yaml"
    raw = SOURCE.replace("\n", newline).encode()
    source.write_bytes(raw)
    url = "/api/workflows/check.yaml"
    assert post(owner, url + "/lease", {"holder": "tab"}).status_code == 200
    document = owner.get(url).json()
    assert document["yaml"] == SOURCE
    assert document["base_hash"] == sha256(raw).hexdigest()
    body = {"holder": "tab", "yaml": SOURCE, "base_hash": document["base_hash"]}
    assert post(owner, url + "/save", body).status_code == 200
    assert source.read_bytes() == raw
    body["yaml"] = SOURCE.replace("Recovery", "Draft")
    assert post(owner, url + "/draft", body).status_code == 200
    document = owner.get(url).json()
    assert document["draft"]["base_hash"] == document["base_hash"]
    foreign = raw.replace(b"Recovery", b"Owner edit")
    source.write_bytes(foreign)
    assert owner.get(url).json()["base_hash"] != document["draft"]["base_hash"]
    assert post(owner, url + "/save", body).status_code == 409
    assert source.read_bytes() == foreign
    body["base_hash"] = sha256(foreign).hexdigest()
    assert post(owner, url + "/save", body).status_code == 200
    assert source.read_bytes() == str(body["yaml"]).replace("\n", newline).encode()


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_prompt_bundle_preserves_newlines_and_refuses_changed_bytes(
    owner: Client, project: RelayProject, newline: str
) -> None:
    prompt = project.write(".relay/prompts/check.md", "")
    raw = f"# Review{newline}Check the change.{newline}".encode()
    prompt.write_bytes(raw)
    document = read_prompt_document(project.relay_root, "prompts/check.md")
    assert document["text"] == "# Review\nCheck the change.\n"
    assert document["base_hash"] == sha256(raw).hexdigest()
    url = "/api/workflows/check.yaml"
    assert post(owner, url + "/lease", {"holder": "tab"}).status_code == 200
    edit = {"text": document["text"], "base_hash": document["base_hash"]}
    body = {
        "holder": "tab",
        "yaml": SOURCE,
        "base_hash": owner.get(url).json()["base_hash"],
        "prompts": {"prompts/check.md": edit},
    }
    assert post(owner, url + "/save", body).status_code == 200
    assert prompt.read_bytes() == raw
    prompt.write_bytes(raw.replace(b"Review", b"Owner"))
    assert post(owner, url + "/save", body).status_code == 409
    assert prompt.read_bytes() == raw.replace(b"Review", b"Owner")
    edit.update(
        text="# Updated\nKeep the style.\n", base_hash=sha256(prompt.read_bytes()).hexdigest()
    )
    assert post(owner, url + "/save", body).status_code == 200
    assert prompt.read_bytes() == f"# Updated{newline}Keep the style.{newline}".encode()


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_individual_prompt_save_preserves_newlines(project: RelayProject, newline: str) -> None:
    path = project.write(".relay/prompts/check.md", "")
    raw = f"Original{newline}Instructions{newline}".encode()
    path.write_bytes(raw)
    document = read_prompt_document(project.relay_root, "prompts/check.md")
    save_prompt_document(
        project.relay_root, "prompts/check.md", "Updated\nInstructions\n", document["base_hash"]
    )
    assert path.read_bytes() == f"Updated{newline}Instructions{newline}".encode()


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_launch_snapshot_retains_exact_workflow_and_prompt_bytes(
    project: RelayProject, newline: str
) -> None:
    text = (
        "version: 1\nname: Snapshot\nnodes:\n"
        "  check: {type: agent, prompts: [{local: prompts/check.md}]}\n"
    )
    workflow = project.write(".relay/workflows/check.yaml", "")
    raw = text.replace("\n", newline).encode()
    workflow.write_bytes(raw)
    prompt = project.write(".relay/prompts/check.md", "")
    prompt_raw = f"First instruction{newline}Second instruction{newline}".encode()
    prompt.write_bytes(prompt_raw)
    loaded = validate_loaded_workflow(load_workflow(workflow), project.relay_root)
    snapshot = build_snapshot(loaded, typed_inputs={}, routes=[])
    assert snapshot.workflow_yaml.encode() == raw
    assert snapshot.hashes["workflow"] == sha256(raw).hexdigest()
    assert snapshot.resolved_prompts[0]["content"].encode() == prompt_raw
    assert snapshot.resolved_prompts[0]["sha256"] == sha256(prompt_raw).hexdigest()
