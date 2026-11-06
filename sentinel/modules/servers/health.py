"""Verificações de saúde (PRD 6.4) e cálculo do estado do servidor (PRD 6.3).

Regra central: processo ativo não significa servidor saudável. Sem verificação
de porta/TCP/HTTP, o estado é "online", mas marcado como não verificado.
"""

from __future__ import annotations

import asyncio
import http.client
import ssl
import time
from dataclasses import dataclass
from typing import Literal

from sentinel.modules.servers.models import BAD_STATES, HealthCheck, ServerState

HealthStatus = Literal["ok", "fail", "timeout", "skipped"]
HEALTH_HOST = "127.0.0.1"  # verificações só no próprio computador


@dataclass(frozen=True, slots=True)
class HealthResult:
    status: HealthStatus
    response_time_ms: float | None = None
    error: str | None = None
    port_listening: bool | None = None


@dataclass(frozen=True, slots=True)
class Observation:
    process_alive: bool
    health: HealthResult


@dataclass(frozen=True, slots=True)
class Evaluation:
    state: ServerState
    failures: int  # falhas consecutivas acumuladas
    health_verified: bool


async def check_health(check: HealthCheck, port: int | None, listeners: dict[int, set[int | None]]) -> HealthResult:
    if check.type == "none" or port is None:
        return HealthResult("skipped", port_listening=(port in listeners) if port else None)
    listening = port in listeners
    if check.type == "port":
        return HealthResult("ok" if listening else "fail", 0.0, None if listening else f"porta {port} não está escutando", listening)
    if check.type == "tcp":
        return await _check_tcp(port, check.timeout_seconds, listening)
    return await asyncio.to_thread(_check_http, check, port, listening)


async def _check_tcp(port: int, timeout: float, listening: bool) -> HealthResult:
    started = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(HEALTH_HOST, port), timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        return HealthResult("ok", _ms(started), None, listening)
    except TimeoutError:
        return HealthResult("timeout", _ms(started), f"sem resposta em {timeout:g}s", listening)
    except OSError as exc:
        return HealthResult("fail", _ms(started), f"conexão recusada: {exc.strerror or exc}", listening)


def _check_http(check: HealthCheck, port: int, listening: bool) -> HealthResult:
    started = time.perf_counter()
    if check.scheme == "https":
        # Servidor local, geralmente com certificado próprio: valida-se disponibilidade, não identidade.
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(HEALTH_HOST, port, timeout=check.timeout_seconds, context=context)
    else:
        conn = http.client.HTTPConnection(HEALTH_HOST, port, timeout=check.timeout_seconds)
    try:
        conn.request("GET", check.path, headers={"User-Agent": "Sentinel-HealthCheck", "Connection": "close"})
        resp = conn.getresponse()
        resp.read(64 * 1024)
        ok = resp.status == check.expected_status if check.expected_status else resp.status < 400
        error = None if ok else f"HTTP {resp.status}"
        return HealthResult("ok" if ok else "fail", _ms(started), error, listening)
    except TimeoutError:
        return HealthResult("timeout", _ms(started), f"sem resposta em {check.timeout_seconds:g}s", listening)
    except (OSError, http.client.HTTPException) as exc:
        return HealthResult("fail", _ms(started), f"{type(exc).__name__}: {exc}", listening)
    finally:
        conn.close()


def evaluate(previous: ServerState, previous_failures: int, obs: Observation, failure_threshold: int = 2) -> Evaluation:
    """Novo estado a partir da observação. Exige ``failure_threshold`` falhas seguidas para
    rebaixar um servidor (evita alarmes por uma leitura isolada); recuperação é imediata."""
    if not obs.process_alive:
        candidate = ServerState.OFFLINE
    elif obs.health.status in ("ok", "skipped"):
        return Evaluation(ServerState.ONLINE, 0, obs.health.status == "ok")
    elif obs.health.status == "timeout":
        candidate = ServerState.UNRESPONSIVE
    else:
        candidate = ServerState.DEGRADED

    failures = previous_failures + 1
    first_observation = previous in (ServerState.UNKNOWN, ServerState.DISABLED)
    if first_observation or previous in BAD_STATES or failures >= failure_threshold:
        return Evaluation(candidate, failures, False)
    return Evaluation(previous, failures, False)  # ainda dentro da tolerância


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
