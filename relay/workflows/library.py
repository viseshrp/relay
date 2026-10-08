"""Owner-managed workflow templates, stored separately from project sources."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import tempfile
from typing import Any
import uuid

from ruamel.yaml import YAML

from relay.errors import WorkflowValidationError
from relay.execution.action_products import checked_path
from relay.execution.resources import _linked
from relay.paths import data_dir, ensure_private_dir, safe_resolve
from relay.vcs.git import run_git

from .actions.compiler import definition
from .actions.language import MAX_YAML_BYTES, capture_sources, load, source_bytes
from .editor import WorkflowDocument, WorkflowEditorStore, _atomic_create, read_workflow_document


def _root() -> Path:
    root = data_dir() / "workflow-library"
    if _linked(root) or _linked(root.parent):
        message = "The workflow library ownership changed."
        raise WorkflowValidationError(message)
    ensure_private_dir(root)
    return root


def import_template(bundle: Mapping[str, Any]) -> str:
    source = bundle.get("yaml")
    metadata = bundle.get("metadata", {})
    sources = bundle.get("sources", {})
    if (
        not isinstance(source, str)
        or not isinstance(metadata, dict)
        or not isinstance(sources, dict)
    ):
        message = "A library bundle requires YAML, metadata, and source mappings."
        raise WorkflowValidationError(message)
    if len(json.dumps(bundle).encode()) > 10 * MAX_YAML_BYTES:
        message = "A workflow library bundle is limited to 10 MiB."
        raise WorkflowValidationError(message)
    if len(sources) > 100:
        message = "A workflow library bundle is limited to 100 source files."
        raise WorkflowValidationError(message)
    if metadata.keys() - {
        "name",
        "description",
        "iconName",
        "categories",
        "filePatterns",
    } or not isinstance(metadata.get("name"), str):
        message = "Template metadata requires name and supported gallery fields."
        raise WorkflowValidationError(message)
    if not metadata["name"] or any(
        not isinstance(metadata.get(field, ""), str) or len(metadata.get(field, "")) > 2048
        for field in ("name", "description", "iconName")
    ):
        message = "Template gallery text must be bounded strings."
        raise WorkflowValidationError(message)
    for field in ("categories", "filePatterns"):
        if field in metadata and (
            not isinstance(metadata[field], list)
            or any(not isinstance(item, str) for item in metadata[field])
        ):
            message = "Template categories and filePatterns must be string lists."
            raise WorkflowValidationError(message)
    document = load(source.replace("$default-branch", "main"))
    for name, value in sources.items():
        if (
            not isinstance(name, str)
            or not isinstance(value, str)
            or not name.startswith((".relay/prompts/", ".relay/actions/", ".relay/workflows/"))
        ):
            message = (
                "Template sources must stay within .relay workflow, action, or prompt folders."
            )
            raise WorkflowValidationError(message)
        safe_resolve(_root(), name)
        if any(part in {"..", ".git"} for part in Path(name).parts):
            message = "Template sources cannot traverse their declared source folders."
            raise WorkflowValidationError(message)
    with tempfile.TemporaryDirectory(prefix="relay-library-validation-") as temporary:
        root = Path(temporary)
        for name, value in sources.items():
            path = checked_path(root, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            raw, mode = source_bytes(value)
            path.write_bytes(raw)
            path.chmod(mode)
        capture_sources(document, root)
    identity = str(uuid.uuid4())
    if len(list(_root().glob("*.json"))) >= 100:
        message = "The owner workflow library is limited to 100 templates."
        raise WorkflowValidationError(message)
    _atomic_create(_root() / f"{identity}.json", json.dumps(dict(bundle), ensure_ascii=False))
    return identity


def export_template(identity: str) -> dict[str, Any]:
    try:
        canonical = str(uuid.UUID(identity.removeprefix("owner:")))
    except ValueError:
        message = "The template identity is invalid."
        raise WorkflowValidationError(message) from None
    path = safe_resolve(_root(), f"{canonical}.json")
    if _linked(path) or not path.is_file() or path.stat().st_size > 10 * MAX_YAML_BYTES:
        message = "The template source is unavailable or too large."
        raise WorkflowValidationError(message)
    return json.loads(path.read_text(encoding="utf-8"))


def inventory() -> list[dict[str, Any]]:
    result = []
    for path in sorted(_root().glob("*.json"))[:100]:
        bundle = export_template(path.stem)
        compiled = definition(load(bundle["yaml"].replace("$default-branch", "main")))
        result.append(
            {
                "id": f"owner:{path.stem}",
                **bundle["metadata"],
                "jobs": list(compiled.nodes),
                "prompts": [],
                "required_agents": "Workflow-defined agents",
                "inputs": {
                    key: item.model_dump(mode="json") for key, item in compiled.inputs.items()
                },
            }
        )
    return result


def instantiate(
    store: WorkflowEditorStore, relay_root: Path, project_id: str, key: str, identity: str
) -> WorkflowDocument:
    from .loader import load_workflow_text, resolve_workflow_path
    from .validation import validate_loaded_workflow

    bundle = export_template(identity)
    branch = (
        run_git(
            relay_root.parent, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], check=False
        )
        .stdout.strip()
        .removeprefix("origin/")
    )
    if not branch:
        branch = (
            run_git(
                relay_root.parent, ["config", "--get", "init.defaultBranch"], check=False
            ).stdout.strip()
            or "main"
        )
    parser = YAML(typ="rt")
    document = parser.load(bundle["yaml"])

    def substitute(value: Any) -> Any:
        if isinstance(value, dict):
            for name, child in value.items():
                value[name] = substitute(child)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                value[index] = substitute(child)
        elif isinstance(value, str):
            return value.replace("$default-branch", branch)
        return value

    output = StringIO()
    parser.width = 80
    parser.dump(substitute(document), output)
    text = output.getvalue()
    target = resolve_workflow_path(relay_root / "workflows", key)
    created: list[tuple[Path, str]] = []
    try:
        for name, source in bundle.get("sources", {}).items():
            raw, mode = source_bytes(source)
            destination = checked_path(relay_root.parent, name)
            if destination.exists():
                if destination.read_bytes() != raw:
                    message = "A template source would replace an owner file."
                    raise WorkflowValidationError(message)  # noqa: TRY301 - rollback follows
            else:
                _atomic_create(destination, raw)
                destination.chmod(mode)
                created.append((destination, sha256(raw).hexdigest()))
        load(text, source=target)
        validate_loaded_workflow(load_workflow_text(text, source=target), relay_root)
        _atomic_create(target, text)
    except Exception:
        for path, digest in reversed(created):
            if (
                not _linked(path)
                and path.is_file()
                and sha256(path.read_bytes()).hexdigest() == digest
            ):
                path.unlink()
        raise
    return read_workflow_document(store, relay_root, project_id, key)
