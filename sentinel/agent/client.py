"""Cliente da API local, usado pela CLI e pelas autoverificações.

Autentica do mesmo jeito que o dashboard: grava um código de uso único no
banco (só possível para quem acessa a pasta do Sentinel) e o troca por uma sessão.
"""

from __future__ import annotations

import asyncio
import http.client
import json
from typing import Any

from sentinel.agent.config import Settings
from sentinel.api.security import SESSION_COOKIE
from sentinel.database.database import Database
from sentinel.database.repositories import AuthRepository


class ApiError(Exception):
    def __init__(self, status: int, detail: Any) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


class LocalClient:
    def __init__(self, settings: Settings, timeout: float = 120.0) -> None:
        self.settings = settings
        host = "127.0.0.1" if settings.api.host == "localhost" else settings.api.host
        self.host = host
        self.port = settings.api.port
        self.host_header = f"[{host}]:{self.port}" if ":" in host else f"{host}:{self.port}"
        self.origin = f"http://{self.host_header}"
        self.timeout = timeout
        self.token: str | None = None

    def raw(self, method: str, path: str, headers: dict[str, str] | None = None, body: bytes | None = None) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            all_headers = {"Host": self.host_header, **(headers or {})}
            conn.request(method, path, body=body, headers=all_headers)
            resp = conn.getresponse()
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
        finally:
            conn.close()

    def login(self) -> tuple[int, dict[str, str], str]:
        """Faz login; retorna (status, cabeçalhos, código usado) para quem quiser inspecionar."""
        code = asyncio.run(create_login_code(self.settings))
        status, headers, _ = self.raw("GET", f"/login?code={code}")
        self.token = cookie_value(headers.get("set-cookie", ""), SESSION_COOKIE)
        return status, headers, code

    def request(self, method: str, path: str, payload: Any = None) -> Any:
        if self.token is None:
            self.login()
        headers = {"Cookie": f"{SESSION_COOKIE}={self.token}", "Origin": self.origin, "X-Sentinel-Client": "cli"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        status, _, data = self.raw(method, path, headers, body)
        parsed = json.loads(data) if data else None
        if status >= 400:
            raise ApiError(status, (parsed or {}).get("detail") if isinstance(parsed, dict) else parsed)
        return parsed


async def create_login_code(settings: Settings) -> str:
    db = Database(settings.paths.database_file, settings.database.busy_timeout_ms)
    await db.open()
    try:
        return await AuthRepository(db).create_login_code(settings.api.login_code_seconds)
    finally:
        await db.close()


def cookie_value(header: str, name: str) -> str | None:
    for part in header.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name and value:
            return value
    return None
