from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from relay.config import default_phase_model_mapping


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


def project_payload(path: str, name: str = "project") -> dict[str, object]:
    now = utc_now()
    return {
        "id": new_id(),
        "name": name,
        "path": path,
        "is_git_repo": False,
        "created_at": now,
        "updated_at": now,
    }


def workflow_run_payload(project_id: str, name: str = "workflow") -> dict[str, object]:
    now = utc_now()
    return {
        "id": new_id(),
        "project_id": project_id,
        "name": name,
        "status": "queued",
        "branch": None,
        "head_commit": None,
        "autopilot": True,
        "review_fix_loop_count": 0,
        "review_fix_loop_limit": 5,
        "retry_limit": 5,
        "phase_model_mapping": json.dumps(default_phase_model_mapping()),
        "context_paths": "[]",
        "finalize_requested": False,
        "cancel_requested": False,
        "pending_fix_prompt": None,
        "created_at": now,
        "updated_at": now,
    }
