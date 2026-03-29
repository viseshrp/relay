from __future__ import annotations

import shutil
from pathlib import Path


PHASE_DIRECTORY_MAP = {
    "exploration": "exploration",
    "planning": "planning",
    "plan_critique": "critique",
    "plan_correction": "planning",
    "execution": "execution",
    "review": "review",
}

PHASE_ATTEMPT_DIRECTORY_MAP = {
    "exploration": "exploration_attempt",
    "planning": "planning_attempt",
    "plan_critique": "critique_attempt",
    "plan_correction": "plan_correction_attempt",
    "execution": "execution_attempt",
    "review": "review_attempt",
}


def relay_root(project_path: str, run_id: str) -> Path:
    return Path(project_path) / ".relay" / run_id


def ensure_artifact_dirs(project_path: str, run_id: str) -> Path:
    root = relay_root(project_path, run_id)
    for directory in {"exploration", "planning", "critique", "execution", "review", "attempts", "exploration/messages"}:
        (root / directory).mkdir(parents=True, exist_ok=True)
    return root


def artifact_dir(project_path: str, run_id: str, phase_type: str) -> Path:
    root = ensure_artifact_dirs(project_path, run_id)
    return root / PHASE_DIRECTORY_MAP[phase_type]


def save_artifact(project_path: str, run_id: str, phase_type: str, filename: str, content: str) -> Path:
    target = artifact_dir(project_path, run_id, phase_type) / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def read_artifact(project_path: str, run_id: str, phase_type: str, filename: str) -> str:
    return (artifact_dir(project_path, run_id, phase_type) / filename).read_text(encoding="utf-8")


def artifact_path(project_path: str, run_id: str, relative_path: str) -> Path:
    return relay_root(project_path, run_id) / relative_path


def archive_attempt(project_path: str, run_id: str, phase_type: str, attempt_number: int) -> Path:
    current_dir = artifact_dir(project_path, run_id, phase_type)
    destination = relay_root(project_path, run_id) / "attempts" / f"{PHASE_ATTEMPT_DIRECTORY_MAP[phase_type]}_{attempt_number}"
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if current_dir.exists():
        for child in current_dir.iterdir():
            if child.is_dir():
                shutil.copytree(child, destination / child.name, dirs_exist_ok=True)
            else:
                shutil.copy2(child, destination / child.name)
    return destination


def check_artifacts_exist(project_path: str, run_id: str, phase_type: str, expected_files: list[str]) -> bool:
    base_dir = artifact_dir(project_path, run_id, phase_type)
    return all((base_dir / filename).exists() for filename in expected_files)
