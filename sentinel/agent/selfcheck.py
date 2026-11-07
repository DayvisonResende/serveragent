"""Autoverificação do agente em execução (``python -m sentinel selfcheck``).

Testa, de fora, o que o usuário depende: API respondendo, proteções de
segurança ativas, login de uso único, dados reais chegando por REST e por
WebSocket e métricas sendo gravadas. Usado pelo verificar.bat.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from typing import Any

from sentinel.agent.client import LocalClient, cookie_value, create_login_code
from sentinel.agent.config import Settings
from sentinel.api.security import SESSION_COOKIE


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def run_selfcheck(settings: Settings) -> list[Check]:
    checks: list[Check] = []
    api = settings.api
    if not api.enabled:
        return [Check("API habilitada", False, "api.enabled está desativado em settings.yaml")]
    http = LocalClient(settings)
    origin = f"http://{http.host_header}"

    def attempt(name: str, fn: Any) -> Any:
        try:
            return fn()
        except Exception as exc:  # cada verificação falha de forma isolada e relatada
            checks.append(Check(name, False, f"{type(exc).__name__}: {exc}"))
            return None

    # 1. disponibilidade
    res = attempt("API respondendo", lambda: http.raw("GET", "/health"))
    if res is None:
        return checks
    checks.append(Check("API respondendo", res[0] == 200, f"GET /health -> {res[0]}"))

    # 2. proteções
    res = attempt("Rotas exigem sessão", lambda: http.raw("GET", "/api/v1/system/status"))
    if res:
        checks.append(Check("Rotas exigem sessão", res[0] == 401, f"sem cookie -> {res[0]}"))
    res = attempt("Host estranho recusado", lambda: http.raw("GET", "/health", {"Host": "attacker.example"}))
    if res:
        checks.append(Check("Host estranho recusado (DNS rebinding)", res[0] == 400, f"-> {res[0]}"))
    res = attempt(
        "Origem estranha recusada",
        lambda: http.raw("POST", "/api/v1/auth/logout", {"Origin": "http://attacker.example"}),
    )
    if res:
        checks.append(Check("Origem estranha recusada (CSRF)", res[0] == 403, f"-> {res[0]}"))

    # 3. login de uso único
    code = attempt("Criar código de login", lambda: asyncio.run(create_login_code(settings)))
    if code is None:
        return checks
    res = attempt("Login com código", lambda: http.raw("GET", f"/login?code={code}"))
    if res is None:
        return checks
    cookie_header = res[1].get("set-cookie", "")
    token = cookie_value(cookie_header, SESSION_COOKIE)
    flags_ok = "httponly" in cookie_header.lower() and "samesite=strict" in cookie_header.lower()
    checks.append(Check("Login com código de uso único", res[0] == 303 and token is not None and flags_ok,
                        f"-> {res[0]}, cookie HttpOnly+SameSite=Strict: {flags_ok}"))
    reuse = attempt("Código não reutilizável", lambda: http.raw("GET", f"/login?code={code}"))
    if reuse:
        checks.append(Check("Código não reutilizável", reuse[0] == 401, f"segundo uso -> {reuse[0]}"))
    if token is None:
        return checks
    auth = {"Cookie": f"{SESSION_COOKIE}={token}"}

    # 4. dados reais
    res = attempt("Status com dados reais", lambda: http.raw("GET", "/api/v1/system/status", auth))
    if res and res[0] == 200:
        data = json.loads(res[2])
        current = data.get("current") or {}
        cpu = (current.get("cpu") or {}).get("percent")
        ok = cpu is not None and 0 <= cpu <= 100 and (current.get("age_seconds") or 999) < 30
        checks.append(Check("Status com dados reais", ok, f"CPU {cpu}%, coleta há {current.get('age_seconds')}s"))
        machine = data.get("machine") or {}
        checks.append(Check("Processador identificado", bool(machine.get("cpu_model")), machine.get("cpu_model") or "não identificado"))
        jobs = [j for j in (data.get("agent") or {}).get("jobs", []) if j.get("load_share") is not None]
        jobs.sort(key=lambda j: j["load_share"], reverse=True)
        if jobs:
            top = ", ".join(f"{j['name']} {j['avg_duration_ms']:.0f} ms/{j['effective_interval_seconds']:.0f} s" for j in jobs[:6])
            checks.append(Check("Custo das tarefas (informativo)", True, top))
        temp = data.get("temperature") or {}
        checks.append(Check("Temperatura (informativo)", True,
                            "sensores disponíveis" if temp.get("available") else (temp.get("message") or "não coletada ainda")))
    elif res:
        checks.append(Check("Status com dados reais", False, f"-> {res[0]}"))

    # 4b. segurança: vigia da inicialização automática e aprovações
    # A primeira varredura começa com o agente e leva alguns segundos (tarefas agendadas e
    # serviços); logo após um reinício ela pode ainda estar em andamento.
    res = attempt("Vigia da inicialização automática", lambda: _wait_first_scan(http, auth))
    if res and res[0] == 200:
        data = json.loads(res[2])
        st = data["status"]
        ok = st.get("last_scan") is not None and st.get("entries", 0) > 0 and not st.get("failed_sources")
        detail = f"{st.get('entries', 0)} itens vigiados"
        if st.get("failed_sources"):
            detail += f"; FONTES INDISPONÍVEIS: {', '.join(st['failed_sources'])}"
        if st.get("errors"):
            detail += f"; avisos: {'; '.join(st['errors'][:3])}"
        if not ok:
            status_res = http.raw("GET", "/api/v1/system/status", auth)
            failing = (json.loads(status_res[2]).get("agent") or {}).get("failing_jobs", []) if status_res[0] == 200 else []
            detail = f"sem varredura completa em 2 min ({detail})" + (f"; tarefas com falha: {', '.join(failing)}" if failing else "")
        checks.append(Check("Vigia da inicialização automática", ok, detail))
        suspicious = [e for e in data.get("entries", []) if e.get("suspicious")]
        checks.append(Check("Itens suspeitos na inicialização (informativo)", True,
                            "nenhum" if not suspicious else " | ".join(f"{e['location']} → {e['name']}: {'; '.join(e['reasons'])}" for e in suspicious[:3])))
    res = attempt("Aprovações", lambda: http.raw("GET", "/api/v1/approvals?status=pending", auth))
    if res and res[0] == 200:
        pending = json.loads(res[2])["pending"]
        checks.append(Check("Aprovações pendentes (informativo)", True, f"{pending} aguardando decisão"))

    # 5. tempo real
    attempt("WebSocket em tempo real", lambda: checks.append(_check_websocket(http, auth["Cookie"], origin, settings)))

    # 6. sessão encerrada
    res = attempt("Logout", lambda: http.raw("POST", "/api/v1/auth/logout", {**auth, "Origin": origin}))
    if res:
        after = http.raw("GET", "/api/v1/auth/session", auth)
        checks.append(Check("Logout invalida a sessão", res[0] == 204 and after[0] == 401, f"-> {res[0]}, depois {after[0]}"))

    # 7. persistência
    attempt("Métricas gravadas no banco", lambda: checks.append(_check_persisted(settings)))
    return checks


def _wait_first_scan(http: LocalClient, auth: dict[str, str], timeout: float = 120.0) -> tuple[int, dict[str, str], bytes]:
    deadline = time.monotonic() + timeout
    while True:
        res = http.raw("GET", "/api/v1/security/autostart", auth)
        if res[0] != 200 or json.loads(res[2])["status"].get("last_scan") is not None or time.monotonic() > deadline:
            return res
        time.sleep(3)


def _check_websocket(http: LocalClient, cookie: str, origin: str, settings: Settings) -> Check:
    from websockets.sync.client import connect

    url = f"ws://{http.host_header}/api/v1/ws"
    wait = settings.monitoring.fast_interval_seconds * 2 + 3
    with connect(url, additional_headers={"Cookie": cookie, "Origin": origin}, open_timeout=10) as ws:
        hello = json.loads(ws.recv(timeout=10))
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            msg = json.loads(ws.recv(timeout=wait))
            if msg.get("type") == "metrics":
                cpu = msg["data"]["cpu"]["percent"]
                return Check("WebSocket em tempo real", hello.get("type") == "hello", f"métrica recebida: CPU {cpu}%")
    return Check("WebSocket em tempo real", False, f"nenhuma métrica em {wait:.0f}s")


def _check_persisted(settings: Settings) -> Check:
    conn = sqlite3.connect(f"file:{settings.paths.database_file}?mode=ro", uri=True)
    try:
        count, last = conn.execute("SELECT COUNT(*), MAX(ts_epoch) FROM system_metrics").fetchone()
    finally:
        conn.close()
    if not count:
        return Check("Métricas gravadas no banco", False, "nenhuma linha em system_metrics")
    return Check("Métricas gravadas no banco", True, f"{count} registros, último há {time.time() - last:.0f}s")


def as_json(checks: list[Check]) -> str:
    return json.dumps([asdict(c) for c in checks], ensure_ascii=True)
