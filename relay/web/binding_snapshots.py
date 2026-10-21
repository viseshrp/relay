"""Capture scoped binding revisions without resolving runtime secret values."""

from __future__ import annotations

from collections.abc import Mapping

from relay.execution.launch_request import (
    FrozenEnvironmentBindings,
    FrozenLaunchBindings,
    FrozenSecretReference,
)
from relay.workflows.actions.language import ActionsDocument, referenced_secrets

from .models import WorkflowBinding, WorkflowEnvironment

UNBOUND_WARNING = (
    "Secret {name} has no binding, so steps receive an empty value. "
    "Add it under Variables, secrets, environments and library."
)


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


def unbound_secret_warnings(project_id: str, document: ActionsDocument) -> list[dict[str, str]]:
    """Name each secret a job reads that no binding in that job's scopes supplies.

    A job sees installation and project secrets plus those of the environment
    it declares. An environment chosen by an expression may resolve to any
    configured environment, so every environment's secrets count for that job.
    """
    environments = list(
        WorkflowEnvironment.objects.filter(project_id=project_id).values_list("name", flat=True)
    )
    shared: set[str] = set()
    by_environment: dict[str, set[str]] = {name: set() for name in environments}
    prefix = f"environment:{project_id}:"
    for scope, name in WorkflowBinding.objects.filter(
        kind="secret",
        scope__in=[*scopes(project_id), *(prefix + name for name in environments)],
    ).values_list("scope", "name"):
        if scope.startswith(prefix):
            by_environment[scope.removeprefix(prefix)].add(name)
        else:
            shared.add(name)
    missing: set[str] = set()
    for job_id, job in document.value["jobs"].items():
        declared = job.get("environment")
        environment = declared.get("name") if isinstance(declared, Mapping) else declared
        bound = shared
        if isinstance(environment, str) and "${{" in environment:
            bound = shared.union(*by_environment.values())
        elif environment:
            bound = shared | by_environment.get(str(environment), set())
        missing |= referenced_secrets(document, job=job_id) - bound
    return [
        {"code": "unbound_secret", "name": name, "message": UNBOUND_WARNING.format(name=name)}
        for name in sorted(missing)
    ]
