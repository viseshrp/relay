"""Per-step Actions files, atomic private job state, and shell rendering."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import tempfile
from typing import Any

from relay.errors import NodeExecutionError, PathSafetyError

MAX_FILE = 1_048_576
MAX_WORKFLOW_OUTPUTS = 50 * MAX_FILE
FILE_NAMES = ("OUTPUT", "ENV", "PATH", "STATE", "STEP_SUMMARY", "ARTIFACTS")


def atomic_state(path: Path, state: Mapping[str, Any]) -> None:
    """Private bytes may contain evaluated secrets; no public payload stores them."""
    if path.is_symlink() or path.parent.is_symlink():
        message = "The private job state was replaced by a link."
        raise PathSafetyError(message)
    descriptor, name = tempfile.mkstemp(prefix=".job-state-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            json.dump(state, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"env": {}, "path": [], "steps": {}, "consumed": [], "subjects": [], "posts": []}
    if path.is_symlink() or path.stat().st_size > 60 * MAX_FILE:
        message = "The private job state is unsafe or oversized."
        raise PathSafetyError(message)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeError):
        message = "The private job state is unreadable."
        raise NodeExecutionError(message) from None
    if not isinstance(value, dict):
        message = "The private job state is invalid."
        raise NodeExecutionError(message)
    return value


def step_files(directory: Path) -> dict[str, Path]:
    result = {}
    for name in FILE_NAMES:
        path = directory / f"github-{name.lower()}"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        result[f"GITHUB_{name}"] = path
    return result


def file_text(path: Path, *, limit: int = MAX_FILE) -> str:
    if path.is_symlink() or not path.is_file():
        message = "An Actions command file was replaced or removed."
        raise PathSafetyError(message)
    try:
        with path.open("rb") as stream:
            content = stream.read(limit + 1)
        if len(content) > limit or b"\x00" in content:
            message = "An Actions command file exceeds its limit or contains NUL."
            raise NodeExecutionError(message)
        return content.decode("utf-8-sig")
    except (OSError, UnicodeError):
        message = "An Actions command file cannot be read as UTF-8."
        raise NodeExecutionError(message) from None


def key_values(text: str) -> dict[str, str]:
    """Parse runner file commands, preserving multiline values and CRLF semantics."""
    lines = text.splitlines(keepends=True)
    result = {}
    index = 0
    while index < len(lines):
        line = lines[index].rstrip("\r\n")
        index += 1
        if not line:
            continue
        equals = line.find("=")
        heredoc = line.find("<<")
        if heredoc >= 0 and (equals < 0 or heredoc < equals):
            name, delimiter = line.split("<<", 1)
            if not name or not delimiter or len(delimiter) > 4096:
                message = "Invalid multiline Actions file command."
                raise NodeExecutionError(message)
            chunks = []
            while index < len(lines) and lines[index].rstrip("\r\n") != delimiter:
                chunks.append(lines[index])
                index += 1
            if index == len(lines):
                message = "Multiline Actions file command has no closing delimiter."
                raise NodeExecutionError(message)
            index += 1
            value = "".join(chunks)
            value = (
                value[:-2]
                if value.endswith("\r\n")
                else value[:-1]
                if value.endswith("\n")
                else value
            )
        elif equals >= 0:
            name, value = line.split("=", 1)
        else:
            message = "Invalid Actions file command."
            raise NodeExecutionError(message)
        if not name or "\x00" in name or "\n" in name or "\r" in name:
            message = "Invalid Actions output name."
            raise NodeExecutionError(message)
        result[name] = value
    return result


def declared_subjects(
    text: str, workspace: Path, previous: list[dict[str, str]]
) -> tuple[list[dict[str, str]], dict[str, str]]:
    subjects = {item["name"]: item for item in previous}
    retained = {}
    for line in text.splitlines():
        reference = line.strip()
        if not reference or reference.startswith("#"):
            continue
        match = re.fullmatch(r"(?:oci://)?(.+)@(sha256|sha384|sha512):([0-9a-f]+)", reference)
        if match:
            name, algorithm, digest = match.groups()
            if len(digest) != {"sha256": 64, "sha384": 96, "sha512": 128}[algorithm]:
                message = "An OCI artifact digest is incomplete."
                raise NodeExecutionError(message)
            subject = {"name": name, "digest": f"{algorithm}:{digest}", "kind": "oci"}
        else:
            from relay.execution.action_products import checked_path

            path = checked_path(workspace, reference.removeprefix("file://"))
            if path.is_symlink() or not path.is_file():
                message = "A declared artifact must be a regular workspace file."
                raise PathSafetyError(message)
            digest = sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(65_536):
                    digest.update(chunk)
            name = path.name
            subject = {"name": name, "digest": f"sha256:{digest.hexdigest()}", "kind": "file"}
            retained[f"subject:{name}"] = path.relative_to(workspace).as_posix()
        if name in subjects and subjects[name] != subject:
            message = "Conflicting workflow artifact declarations."
            raise NodeExecutionError(message)
        subjects[name] = subject
        if len(subjects) > 500:
            message = "A job exceeds 500 workflow artifact subjects."
            raise NodeExecutionError(message)
    return sorted(subjects.values(), key=lambda item: item["name"]), retained


def consume(
    state: dict[str, Any], attempt_id: str, paths: Mapping[str, Path], workspace: Path
) -> tuple[dict[str, str], dict[str, str], str]:
    """Apply file changes once; the caller atomically persists the returned state."""
    if attempt_id in state["consumed"]:
        return {}, {}, ""
    outputs = key_values(file_text(paths["GITHUB_OUTPUT"]))
    if (
        sum(
            len(name.encode("utf-16-le")) + len(value.encode("utf-16-le"))
            for name, value in outputs.items()
        )
        > MAX_FILE
    ):
        message = "Step outputs exceed the job's 1 MiB output limit."
        raise NodeExecutionError(message)
    environment = key_values(file_text(paths["GITHUB_ENV"]))
    for name, value in environment.items():
        if name.upper().startswith(("GITHUB_", "RUNNER_")) or name.upper() == "NODE_OPTIONS":
            message = "An Actions file attempted to replace a protected variable."
            raise NodeExecutionError(message)
        if "=" in name or "\x00" in value:
            message = "An Actions environment value is invalid."
            raise NodeExecutionError(message)
    state["env"].update(environment)
    for value in file_text(paths["GITHUB_PATH"]).splitlines():
        if value:
            state["path"] = [value, *[item for item in state["path"] if item != value]]
    subjects, retained = declared_subjects(
        file_text(paths["GITHUB_ARTIFACTS"]), workspace, state["subjects"]
    )
    state["subjects"] = subjects
    state["consumed"].append(attempt_id)
    return outputs, retained, file_text(paths["GITHUB_STEP_SUMMARY"])


def shell_script(directory: Path, source: str, shell: str | None) -> list[str]:
    """Render a private script, then select an explicit interpreter argument vector."""
    if shell is None:
        shell = "pwsh" if os.name == "nt" else "bash" if shutil.which("bash") else "sh"
        implicit = True
    else:
        implicit = False
    suffix = {
        "bash": ".sh",
        "sh": ".sh",
        "pwsh": ".ps1",
        "powershell": ".ps1",
        "cmd": ".cmd",
        "python": ".py",
    }.get(shell, ".script")
    path = directory / f"script{suffix}"
    if shell in {"pwsh", "powershell"}:
        source = (
            "$ErrorActionPreference = 'stop'\n"
            + source
            + "\nif ((Test-Path -LiteralPath variable:\\LASTEXITCODE)) { exit $LASTEXITCODE }\n"
        )
    elif shell == "cmd":
        source = "@echo off\r\n" + source.replace("\r\n", "\n").replace("\n", "\r\n")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
        stream.write(source)
    if shell == "bash":
        arguments = (
            ["bash", "-e", str(path)]
            if implicit
            else ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", str(path)]
        )
    elif shell == "sh":
        arguments = ["sh", "-e", str(path)]
    elif shell in {"pwsh", "powershell"}:
        arguments = [shell, "-command", f". '{str(path).replace(chr(39), chr(39) * 2)}'"]
    elif shell == "cmd":
        arguments = ["cmd.exe", "/D", "/E:ON", "/V:OFF", "/S", "/C", f'call "{path}"']
    elif shell == "python":
        import sys

        arguments = [sys.executable, str(path)]
    else:
        arguments = shlex.split(shell)
        if sum(argument.count("{0}") for argument in arguments) != 1:
            message = "A custom shell must contain exactly one {0} script placeholder."
            raise NodeExecutionError(message)
        arguments = [argument.replace("{0}", str(path)) for argument in arguments]
    executable = shutil.which(arguments[0])
    if executable is None:
        message = "The requested shell is not installed."
        raise NodeExecutionError(message)
    arguments[0] = executable
    return arguments
