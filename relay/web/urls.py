"""Authenticated Relay API routes and packaged SPA fallback."""

from django.urls import URLPattern, URLResolver, path

from .static_view import serve_spa
from .views import actions, pages

urlpatterns: list[URLPattern | URLResolver] = [
    path("api/auth", actions.authentication_state, name="auth-state"),
    path("api/auth/onboard", actions.onboard, name="auth-onboard"),
    path("api/auth/login", actions.sign_in, name="auth-login"),
    path("api/auth/logout", actions.sign_out, name="auth-logout"),
    path("api/projects", pages.projects, name="projects"),
    path("api/projects/open", actions.open_project, name="project-open"),
    path("api/projects/relink", actions.relink_registered_project, name="project-relink"),
    path("api/workflows/<path:key>/draft", actions.autosave_draft, name="workflow-draft"),
    path("api/workflows/<path:key>/save", actions.save_workflow, name="workflow-save"),
    path("api/workflows/<path:key>/lease", actions.acquire_workflow_lease, name="workflow-lease"),
    path("api/workflows/<path:key>", pages.workflow, name="workflow"),
    path("api/agents", pages.agents, name="agents"),
    path("api/runs", actions.runs_collection, name="runs"),
    path("api/runs/<str:run_id>", pages.run_detail, name="run-detail"),
    path("api/runs/<str:run_id>/events", pages.run_events, name="run-events"),
    path("api/runs/<str:run_id>/artifacts", pages.run_artifacts, name="run-artifacts"),
    path("api/runs/<str:run_id>/cancel", actions.cancel_run, name="run-cancel"),
    path("api/runs/<str:run_id>/rerun-node", actions.rerun_node, name="run-rerun-node"),
    path(
        "api/attempts/<str:attempt_id>/permission",
        actions.answer_permission,
        name="attempt-permission",
    ),
    path(
        "api/attempts/<str:attempt_id>/elicitation",
        actions.answer_elicitation,
        name="attempt-elicitation",
    ),
    path("api/attempts/<str:attempt_id>/wait", actions.answer_wait, name="attempt-wait"),
    path("api/artifacts/<str:artifact_id>", pages.artifact, name="artifact"),
    path("api/data/clean", actions.clean_data, name="data-clean"),
    path("api/<path:path>", pages.api_not_found, name="api-not-found"),
    path("", serve_spa, name="spa-root"),
    path("<path:asset_path>", serve_spa, name="spa"),
]
