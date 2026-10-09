"""Scoped variable and secret references; secret bytes never enter database rows."""

from __future__ import annotations

from collections.abc import Mapping
import os
import re
from typing import Any, cast
import uuid

from relay.errors import ConfigError
from relay.execution.masking import redactor
from relay.execution.native_credentials import credential

from .models import WorkflowBinding, WorkflowEnvironment

NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def scopes(project_id: str, environment: str | None = None) -> tuple[str, ...]:
    return (
        "installation",
        f"project:{project_id}",
        *((f"environment:{project_id}:{environment}",) if environment else ()),
    )


def put_binding(
    scope: str, name: str, kind: str, *, source: str = "", reference: str = "", value: str = ""
) -> None:
    name = name.upper()
    if (
        not NAME.fullmatch(name)
        or len(name) > 100
        or name.startswith("RELAY_")
        or kind not in {"variable", "secret"}
    ):
        message = "Invalid variable or secret name."
        raise ConfigError(message)
    if len(value.encode()) > 49152:
        message = "Values are limited to 48 KiB."
        raise ConfigError(message)
    revision = uuid.uuid4()
    if (
        not WorkflowBinding.objects.filter(scope=scope, kind=kind, name=name).exists()
        and WorkflowBinding.objects.filter(scope=scope, kind=kind).count() >= 100
    ):
        message = "Each scope is limited to 100 variables and 100 secrets."
        raise ConfigError(message)
    if kind == "secret":
        if source == "environment":
            if not NAME.fullmatch(reference) or len(reference) > 256 or value:
                message = "An environment secret requires an environment variable name."
                raise ConfigError(message)
        elif source == "credential-store":
            reference = f"{scope}/{name}/{revision}"
            credential("set", reference, value)
        else:
            message = "Select environment or credential-store for a secret."
            raise ConfigError(message)
        value = ""
    else:
        source, reference = "", ""
    WorkflowBinding.objects.update_or_create(
        scope=scope,
        name=name,
        kind=kind,
        defaults={"value": value, "source": source, "reference": reference, "revision": revision},
    )


def freeze_bindings(project_id: str) -> dict[str, Any]:
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
    secret_refs: dict[str, Any] = {}
    environment_bindings: dict[str, Any] = {}
    rows = list(
        WorkflowBinding.objects.filter(scope__in=allowed).values(
            "scope", "name", "kind", "value", "source", "reference", "revision"
        )
    )
    for scope in allowed:
        target: dict[str, Any] = (
            environment_bindings.setdefault(scope.split(":", 2)[-1], {"vars": {}, "secrets": {}})
            if scope.startswith("environment:")
            else {"vars": variables, "secrets": secret_refs}
        )
        for row in rows:
            if row["scope"] != scope:
                continue
            if row["kind"] == "variable":
                target["vars"][row["name"]] = row["value"]
            else:
                target["secrets"][row["name"]] = {
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


def resolve_secrets(
    context: Mapping[str, Any], run_id: str, environment: str | None = None
) -> dict[str, str]:
    references = {
        **context.get("secret_refs", {}),
        **context.get("environment_bindings", {}).get(environment, {}).get("secrets", {}),
    }
    result = {}
    for name, row in references.items():
        value = (
            os.environ.get(row["reference"])
            if row["source"] == "environment"
            else credential("get", row["reference"])
        )
        if value is None:
            message = f"Secret {name!r} is unavailable."
            raise ConfigError(message)
        result[name] = value
        redactor(run_id).register(value)
    return result


def job_secrets(
    run_id: str, scope: str, environment: str | None = None, *, ancestors: tuple[str, ...] = ()
) -> dict[str, str]:
    """Resolve frozen references and caller contracts without persisting secret bytes."""
    from relay.workflows.actions import expressions
    from relay.workflows.actions.language import events

    from .actions_repository import scope_context
    from .models import NodeRun

    if scope in ancestors or len(ancestors) >= 10:
        message = "The reusable secret scope is cyclic or too deep."
        raise ConfigError(message)
    frozen = NodeRun.objects.values_list("frozen_def", flat=True).get(
        run_id=run_id, scope_path=scope
    )
    values = scope_context(run_id, scope)
    caller_scope = frozen.get("caller_secret_scope")
    if caller_scope:
        caller = NodeRun.objects.values_list("frozen_def", flat=True).get(
            run_id=run_id, scope_path=caller_scope
        )
        caller_values = scope_context(run_id, caller_scope)
        inherited = job_secrets(run_id, caller_scope, ancestors=(*ancestors, scope))
        supplied = frozen.get("caller_secret_mapping")
        if supplied is None:
            supplied = caller["job"].get("secrets", {})
        if supplied == "inherit":
            result = inherited
        else:
            resolved = expressions.interpolate(supplied, {**caller_values, "secrets": inherited})
            result = {
                name: expressions.string(value)
                for name, value in cast(dict[str, Any], resolved).items()
            }
        declared = events(frozen["workflow"]).get("workflow_call", {}).get("secrets", {})
        if supplied != "inherit" and set(result) - set(declared):
            message = "The caller supplied an undeclared reusable-workflow secret."
            raise ConfigError(message)
        if any(item.get("required") and name not in result for name, item in declared.items()):
            message = "A required reusable-workflow secret was not supplied."
            raise ConfigError(message)
    else:
        result = resolve_secrets(values["_context"], run_id)
    if environment:
        result = {
            **result,
            **resolve_secrets({**values["_context"], "secret_refs": {}}, run_id, environment),
        }
    for value in result.values():
        redactor(run_id).register(value)
    return result
