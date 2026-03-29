import asyncio

from fastapi.testclient import TestClient

from relay.api.app import create_app


def test_websocket_receives_broadcast(test_settings) -> None:
    app = create_app(test_settings)
    with TestClient(app) as client:
      with client.websocket_connect("/api/v1/ws") as websocket:
        websocket.send_json({"type": "subscribe_all"})
        asyncio.run(
            app.state.connection_manager.broadcast(
                {"type": "workflow_status", "run_id": "abc", "status": "running", "timestamp": ""},
                "abc",
            )
        )
        payload = websocket.receive_json()
        assert payload["type"] == "workflow_status"
