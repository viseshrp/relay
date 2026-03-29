import pytest

from relay.schemas.settings import UserSettingsUpdateRequest


@pytest.mark.asyncio
async def test_run_override_beats_project_and_global(app, project_dir) -> None:
    async with app.state.db.session() as session:
        project = await app.state.project_service.create_project(session, str(project_dir))
        await app.state.settings_service.update_user_settings(
            session,
            UserSettingsUpdateRequest(phase_model_mapping={"execution": "gpt-4o"}),
        )
        await app.state.settings_service.update_project_settings(
            session,
            project.id,
            {"execution": "claude-sonnet-4"},
            None,
            None,
            None,
        )
        resolved = await app.state.settings_service.resolve_run_settings(
            session,
            project.id,
            phase_model_mapping={"execution": "o3-mini"},
            retry_limit=None,
            review_fix_loop_limit=None,
            autopilot=None,
        )

    assert resolved.phase_model_mapping["execution"] == "o3-mini"


@pytest.mark.asyncio
async def test_project_override_beats_global(app, project_dir) -> None:
    async with app.state.db.session() as session:
        project = await app.state.project_service.create_project(session, str(project_dir))
        await app.state.settings_service.update_user_settings(
            session,
            UserSettingsUpdateRequest(phase_model_mapping={"review": "gpt-4.1"}),
        )
        await app.state.settings_service.update_project_settings(
            session,
            project.id,
            {"review": "claude-3.5-sonnet"},
            None,
            None,
            None,
        )
        resolved = await app.state.settings_service.resolve_run_settings(
            session,
            project.id,
            phase_model_mapping=None,
            retry_limit=None,
            review_fix_loop_limit=None,
            autopilot=None,
        )

    assert resolved.phase_model_mapping["review"] == "claude-3.5-sonnet"


@pytest.mark.asyncio
async def test_global_setting_beats_application_default(app, project_dir) -> None:
    async with app.state.db.session() as session:
        project = await app.state.project_service.create_project(session, str(project_dir))
        await app.state.settings_service.update_user_settings(
            session,
            UserSettingsUpdateRequest(retry_limit=8),
        )
        resolved = await app.state.settings_service.resolve_run_settings(
            session,
            project.id,
            phase_model_mapping=None,
            retry_limit=None,
            review_fix_loop_limit=None,
            autopilot=None,
        )

    assert resolved.retry_limit == 8


@pytest.mark.asyncio
async def test_missing_override_falls_through_to_next_level(app, project_dir) -> None:
    async with app.state.db.session() as session:
        project = await app.state.project_service.create_project(session, str(project_dir))
        await app.state.settings_service.update_user_settings(
            session,
            UserSettingsUpdateRequest(review_fix_loop_limit=9),
        )
        await app.state.settings_service.update_project_settings(session, project.id, {}, None, None, None)
        resolved = await app.state.settings_service.resolve_run_settings(
            session,
            project.id,
            phase_model_mapping=None,
            retry_limit=None,
            review_fix_loop_limit=None,
            autopilot=None,
        )

    assert resolved.review_fix_loop_limit == 9


@pytest.mark.asyncio
async def test_empty_string_model_is_preserved_as_override(app, project_dir) -> None:
    async with app.state.db.session() as session:
        project = await app.state.project_service.create_project(session, str(project_dir))
        await app.state.settings_service.update_user_settings(
            session,
            UserSettingsUpdateRequest(phase_model_mapping={"execution": "gpt-4o"}),
        )
        await app.state.settings_service.update_project_settings(
            session,
            project.id,
            {"execution": ""},
            None,
            None,
            None,
        )
        resolved = await app.state.settings_service.resolve_run_settings(
            session,
            project.id,
            phase_model_mapping=None,
            retry_limit=None,
            review_fix_loop_limit=None,
            autopilot=None,
        )

    assert resolved.phase_model_mapping["execution"] == ""
