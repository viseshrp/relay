from __future__ import annotations

import pytest

from relay.copilot.detection import CopilotStatus


@pytest.mark.asyncio
async def test_system_status_includes_available_model_catalog(app, client, monkeypatch) -> None:
    async def fake_detect_copilot_status(_settings: object) -> CopilotStatus:
        return CopilotStatus(
            gh_available=True,
            copilot_available=True,
            authenticated=True,
            gh_path="copilot",
            copilot_version="1.0.0",
            auth_details="tester",
            message="ok",
        )

    monkeypatch.setattr("relay.api.system.detect_copilot_status", fake_detect_copilot_status)
    app.state.available_copilot_models = [
        {"id": "", "name": "Default (Copilot default)"},
        {"id": "gpt-5.4", "name": "GPT-5.4"},
    ]

    response = await client.get("/api/v1/system/status")

    assert response.status_code == 200
    assert response.json()["copilot"]["available_models"] == [
        {"id": "", "name": "Default (Copilot default)"},
        {"id": "gpt-5.4", "name": "GPT-5.4"},
    ]
