"""Proteções da API local (PRD 17.2–17.5).

Mesmo escutando apenas em 127.0.0.1, uma API local pode ser atacada pelo
navegador do próprio usuário:
- **DNS rebinding:** um site malicioso faz seu domínio apontar para 127.0.0.1.
  Defesa: o cabeçalho ``Host`` precisa ser exatamente 127.0.0.1/localhost/[::1]
  na porta configurada.
- **CSRF / WebSocket entre sites:** outra página tenta enviar requisições.
  Defesa: cookie ``SameSite=Strict`` + ``Origin`` precisa ser o próprio
  dashboard em requisições que alteram estado e em WebSockets.
- **Acesso por outros processos/usuários:** exige sessão criada por um código
  de uso único que só quem executa o Sentinel na máquina consegue gerar.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from typing import Any, Awaitable, Callable, MutableMapping

from sentinel.database.repositories.auth import AuthRepository, hash_secret

log = logging.getLogger(__name__)

SESSION_COOKIE = "sentinel_session"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def allowed_hosts(port: int) -> frozenset[str]:
    return frozenset({f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"})


def allowed_origins(port: int) -> frozenset[str]:
    return frozenset(f"http://{h}" for h in allowed_hosts(port))


def content_security_policy(port: int) -> str:
    ws = " ".join(f"ws://{h}" for h in sorted(allowed_hosts(port)))
    return (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        f"connect-src 'self' {ws}; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )


class GuardMiddleware:
    """Valida Host e Origin antes de qualquer rota e adiciona cabeçalhos de segurança."""

    def __init__(self, app: ASGIApp, port: int) -> None:
        self.app = app
        self.hosts = allowed_hosts(port)
        self.origins = allowed_origins(port)
        self.security_headers = [
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"referrer-policy", b"no-referrer"),
            (b"content-security-policy", content_security_policy(port).encode()),
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        host = headers.get("host", "").lower()
        if host not in self.hosts:
            log.warning("Requisição recusada: Host não permitido", extra={"host": host[:100]})
            await self._reject(scope, send, 400, "Host não permitido")
            return

        origin = headers.get("origin")
        needs_origin_check = scope["type"] == "websocket" or scope.get("method", "GET") not in SAFE_METHODS
        if needs_origin_check and origin is not None and origin.lower() not in self.origins:
            log.warning("Requisição recusada: Origin não permitida", extra={"origin": origin[:100]})
            await self._reject(scope, send, 403, "Origem não permitida")
            return

        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return

        is_api = scope.get("path", "").startswith("/api/")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                extra = list(self.security_headers)
                extra.append((b"cache-control", b"no-store" if is_api else b"no-cache"))
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        await self.app(scope, receive, send_with_headers)

    @staticmethod
    async def _reject(scope: Scope, send: Send, status: int, detail: str) -> None:
        if scope["type"] == "websocket":
            # Fechar antes de aceitar faz o servidor responder 403 ao handshake.
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json; charset=utf-8"), (b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})


class LoginRateLimiter:
    """Limita tentativas de login falhas (PRD 17.4) numa janela deslizante."""

    def __init__(self, max_failures: int = 20, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self._max = max_failures
        self._window = window_seconds
        self._clock = clock
        self._failures: deque[float] = deque()

    def blocked(self) -> bool:
        now = self._clock()
        while self._failures and now - self._failures[0] > self._window:
            self._failures.popleft()
        return len(self._failures) >= self._max

    def record_failure(self) -> None:
        self._failures.append(self._clock())


class SessionAuth:
    """Sessões do dashboard. Validações recentes ficam em cache por poucos segundos
    para não consultar o banco a cada requisição."""

    def __init__(self, repo: AuthRepository, session_ttl_seconds: float, cache_seconds: float = 30.0) -> None:
        self._repo = repo
        self._ttl = session_ttl_seconds
        self._cache_seconds = cache_seconds
        self._cache: dict[str, tuple[float, float]] = {}  # hash → (expira em, validado em)
        self.limiter = LoginRateLimiter()

    @property
    def ttl_seconds(self) -> float:
        return self._ttl

    async def login(self, code: str) -> tuple[str, float] | None:
        if not code or len(code) > 200 or not await self._repo.consume_login_code(code):
            self.limiter.record_failure()
            return None
        return await self._repo.create_session(self._ttl)

    async def is_valid(self, token: str | None) -> bool:
        if not token or len(token) > 200:
            return False
        key = hash_secret(token)
        now = time.time()
        cached = self._cache.get(key)
        if cached and cached[0] > now and now - cached[1] < self._cache_seconds:
            return True
        expiry = await self._repo.session_expiry(token)
        if expiry is None:
            self._cache.pop(key, None)
            return False
        if len(self._cache) > 1000:
            self._cache.clear()
        self._cache[key] = (expiry, now)
        return True

    async def logout(self, token: str | None) -> None:
        if not token:
            return
        self._cache.pop(hash_secret(token), None)
        await self._repo.delete_session(token)
