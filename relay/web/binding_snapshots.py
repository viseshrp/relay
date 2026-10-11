"""Capture scoped binding revisions without resolving runtime secret values."""

from __future__ import annotations

from relay.execution.launch_request import (
    FrozenEnvironmentBindings,
    FrozenLaunchBindings,
    FrozenSecretReference,
)

from .models import WorkflowBinding, WorkflowEnvironment


def scopes(project_id: str, environment: str | None = None) -> tuple[str, ...]:
    return (
        "installation",
        f"project:{project_id}",
        *((f"environment:{project_id}:{environment}",) if environment else ()),
    )


def freeze_bindings(project_id: str) -> FrozenLaunchBindings:
    allowed = [
        *scopes(project_id),
        *(
            f"environment:{project_id}:{name}"
            for name in WorkflowEnvironment.objects.filter(project_id=project_id).values_list(
                "name", flat=True
            )
        ),
    ]
    variables: dict[str, str] = {}
    secret_refs: dict[str, FrozenSecretReference] = {}
    environment_bindings: dict[str, FrozenEnvironmentBindings] = {}
    rows = list(
        WorkflowBinding.objects.filter(scope__in=allowed).values(
            "scope", "name", "kind", "value", "source", "reference", "revision"
        )
    )
    for scope in allowed:
        if scope.startswith("environment:"):
            target = environment_bindings.setdefault(
                scope.split(":", 2)[-1], {"vars": {}, "secrets": {}}
            )
            target_vars, target_secrets = target["vars"], target["secrets"]
        else:
            target_vars, target_secrets = variables, secret_refs
        for row in rows:
            if row["scope"] != scope:
                continue
            if row["kind"] == "variable":
                target_vars[row["name"]] = row["value"]
            else:
                target_secrets[row["name"]] = {
                    "source": row["source"],
                    "reference": row["reference"],
                    "revision": str(row["revision"]),
                }
    environments = {
        row["name"]: {**row, "id": str(row["id"])}
        for row in WorkflowEnvironment.objects.filter(project_id=project_id).values(
            "id", "name", "approval_required", "wait_minutes", "branches", "url"
        )
    }
    return {
        "vars": variables,
        "secret_refs": secret_refs,
        "environment_bindings": environment_bindings,
        "environments": environments,
    }
