"""API de notificações: o token entra mas nunca sai; validações; detecção de chat; teste."""

import sqlite3

import pytest

from sentinel.agent.client import ApiError, LocalClient
from sentinel.modules.notifications.channels import TelegramChannel
from tests.integration.test_servers_e2e import RunningAgent, fast_settings  # noqa: F401 (fixture)
from tests.unit.test_notifications import TOKEN, FakeTelegram


def test_notification_settings_never_return_the_token(fast_settings):  # noqa: F811
    agent = RunningAgent(fast_settings)
    fake = FakeTelegram()
    agent.agent.registry._entries["notifications"].module._channel = TelegramChannel(fake)
    try:
        client = LocalClient(fast_settings)
        initial = client.request("GET", "/api/v1/settings/notifications")
        assert initial["config"]["enabled"] is False and initial["token"]["configured"] is False

        with pytest.raises(ApiError) as exc:
            client.request("PUT", "/api/v1/settings/notifications", {"telegram_token": "token-errado"})
        assert exc.value.status == 422
        with pytest.raises(ApiError) as exc:
            client.request("PUT", "/api/v1/settings/notifications", {"enabled": True, "telegram_token": TOKEN})
        assert exc.value.status == 422 and "chat" in exc.value.detail

        detected = client.request("POST", "/api/v1/settings/notifications/detect-chats", {"telegram_token": TOKEN})
        assert detected["chats"][0]["id"] == 42

        saved = client.request("PUT", "/api/v1/settings/notifications",
                               {"enabled": True, "telegram_token": TOKEN, "telegram_chat_id": 42})
        assert saved["config"]["enabled"] and saved["token"]["configured"] and saved["status"]["active"]
        assert TOKEN not in str(saved)
        assert TOKEN not in str(client.request("GET", "/api/v1/settings/notifications"))

        # Alterar outras opções sem reenviar o token mantém o token.
        kept = client.request("PUT", "/api/v1/settings/notifications",
                              {"enabled": True, "telegram_chat_id": 42, "min_severity": "critical"})
        assert kept["token"]["configured"] and kept["config"]["min_severity"] == "critical"

        assert client.request("POST", "/api/v1/settings/notifications/test")["ok"] is True
        assert any("Teste do Sentinel" in t for t in fake.sent)

        conn = sqlite3.connect(fast_settings.paths.database_file)
        audit = " ".join(r[0] for r in conn.execute("SELECT details_json FROM audit_logs WHERE operation = 'settings.notifications'"))
        stored = conn.execute("SELECT value FROM secrets").fetchone()[0]
        conn.close()
        assert TOKEN not in audit and '"token": "alterado"' in audit
        assert stored  # existe (cifrado no Windows)
    finally:
        agent.stop()
