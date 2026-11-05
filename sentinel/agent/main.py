"""Linha de comando do Sentinel.

    python -m sentinel init          prepara configuração, diretórios e banco
    python -m sentinel run           executa o agente em primeiro plano
    python -m sentinel status        mostra a última execução e eventos recentes
    python -m sentinel check-config  valida e exibe a configuração efetiva
    python -m sentinel dashboard     abre o dashboard no navegador (login de uso único)
    python -m sentinel stop          pede ao agente em execução que encerre de forma limpa
    python -m sentinel selfcheck     testa API, segurança, tempo real e gravação de métricas
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

from sentinel import __version__
from sentinel.agent import bootstrap
from sentinel.agent.config import PROJECT_ROOT, Settings, load_settings, resolve_config_path
from sentinel.agent.lifecycle import Agent
from sentinel.agent.logging_setup import configure_logging
from sentinel.core.clock import utc_now
from sentinel.core.event_bus import EventType
from sentinel.core.exceptions import ConfigurationError, DatabaseError, InstanceLockError, SentinelError
from sentinel.database.database import Database
from sentinel.database.repositories import AgentRunRepository, AuthRepository, EventRepository
from sentinel.oslayer.info import get_platform_info
from sentinel.oslayer.instance_lock import InstanceLock
from sentinel.oslayer.shutdown_listener import ShutdownListener
from sentinel.oslayer.signals import install_stop_handlers

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CONFIG = 2
EXIT_LOCKED = 3
EXIT_DATABASE = 4

LOCK_FILE_NAME = "sentinel.lock"
STARTUP_ERROR_FILE = "startup-error.log"
# Antes de a configuração ser lida, erros vão para a pasta de logs padrão.
DEFAULT_ERROR_LOG_DIR = PROJECT_ROOT / "logs"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentinel", description="Agente Sentinel")
    parser.add_argument("--version", action="version", version=f"sentinel {__version__}")
    parser.add_argument("--config", type=Path, help="caminho do settings.yaml (padrão: config/settings.yaml)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="prepara configuração, diretórios e banco de dados")
    commands.add_parser("run", help="executa o agente em primeiro plano")
    status_parser = commands.add_parser("status", help="mostra a última execução e os eventos recentes")
    status_parser.add_argument("--json", action="store_true", help="saída em JSON (ASCII), para scripts")
    commands.add_parser("check-config", help="valida e exibe a configuração efetiva")
    dash = commands.add_parser("dashboard", help="abre o dashboard no navegador com um login de uso único")
    dash.add_argument("--no-browser", action="store_true", help="apenas imprime o link")
    stop_parser = commands.add_parser("stop", help="pede ao agente em execução que encerre de forma limpa")
    stop_parser.add_argument("--timeout", type=float, default=20.0, help="segundos para aguardar o encerramento")
    check_parser = commands.add_parser("selfcheck", help="testa a API, a segurança e o tempo real do agente em execução")
    check_parser.add_argument("--json", action="store_true", help="saída em JSON (ASCII), para scripts")
    args = parser.parse_args(argv)

    error_log_dir = DEFAULT_ERROR_LOG_DIR
    try:
        if args.command == "init":
            return cmd_init(args.config)
        settings = load_settings(args.config)
        error_log_dir = settings.paths.log_dir
        if args.command == "run":
            return cmd_run(settings)
        if args.command == "status":
            return cmd_status(settings, as_json=args.json)
        if args.command == "selfcheck":
            return cmd_selfcheck(settings, as_json=args.json)
        if args.command == "stop":
            return cmd_stop(settings, args.timeout)
        if args.command == "dashboard":
            return cmd_dashboard(settings, open_browser=not args.no_browser)
        if args.command == "check-config":
            print(json.dumps(settings.model_dump(mode="json"), indent=2, ensure_ascii=False))
            return EXIT_OK
    except ConfigurationError as exc:
        return _fail(f"Erro de configuração: {exc}", EXIT_CONFIG, error_log_dir)
    except InstanceLockError as exc:
        return _fail(str(exc), EXIT_LOCKED, error_log_dir)
    except DatabaseError as exc:
        return _fail(f"Erro de banco de dados: {exc}", EXIT_DATABASE, error_log_dir)
    except SentinelError as exc:
        return _fail(str(exc), EXIT_ERROR, error_log_dir)
    except Exception as exc:
        logging.getLogger("sentinel").exception("Erro inesperado")
        return _fail(f"Erro inesperado: {type(exc).__name__}: {exc}", EXIT_ERROR, error_log_dir)
    parser.error(f"comando desconhecido: {args.command}")
    return EXIT_ERROR


def cmd_init(config_path: Path | None) -> int:
    path = resolve_config_path(config_path)
    created = bootstrap.write_default_config(path)
    settings = load_settings(path)
    bootstrap.ensure_directories(settings)
    applied, integrity = asyncio.run(bootstrap.initialize_database(settings))
    info = get_platform_info()

    print(f"Sentinel {__version__}")
    print(f"  Configuração : {path} ({'criada' if created else 'existente'})")
    print(f"  Banco        : {settings.paths.database_file}")
    print(f"  Migrações    : {', '.join(f'{v:04d}' for v in applied) if applied else 'nenhuma pendente'}")
    print(f"  Integridade  : {', '.join(integrity)}")
    print(f"  Sistema      : {info.system} {info.release} ({info.machine}), Python {info.python_version}")
    if info.is_admin:
        print("  ATENÇÃO      : executando como administrador. O Sentinel deve rodar sem privilégios elevados.")
    elif info.is_admin is None:
        print("  Privilégios  : não foi possível determinar")
    return EXIT_OK if integrity == ["ok"] else EXIT_DATABASE


def cmd_run(settings: Settings) -> int:
    configure_logging(settings.logging, settings.paths.log_dir)
    bootstrap.ensure_directories(settings)
    with InstanceLock(settings.paths.data_dir / LOCK_FILE_NAME):
        asyncio.run(_run_agent(settings))
    return EXIT_OK


def build_agent(settings: Settings) -> Agent:
    """Raiz de composição: cria o agente e conecta os módulos."""
    from sentinel.api.server import ApiModule
    from sentinel.modules.monitor import MetricsStore, MonitorModule

    m = settings.monitoring
    store = MetricsStore(live_capacity=int(m.live_history_seconds / m.fast_interval_seconds) + 1)
    monitor = MonitorModule(store)
    agent = Agent(settings, modules=[monitor])
    if settings.api.enabled:
        agent.registry.register(
            ApiModule(store, agent.health_report, lambda: monitor.alerts.active() if monitor.alerts else [])
        )
    return agent


async def _run_agent(settings: Settings) -> None:
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    agent = build_agent(settings)
    install_stop_handlers(loop, lambda: agent.request_stop(stop))

    finished = threading.Event()
    listener = ShutdownListener(
        lambda kind: loop.call_soon_threadsafe(agent.request_stop, stop, "system_shutdown", kind),
        finished.wait,
    )
    listener.start()
    try:
        await agent.run(stop)
    finally:
        finished.set()
        listener.stop()


def cmd_selfcheck(settings: Settings, as_json: bool = False) -> int:
    from sentinel.agent.selfcheck import as_json as checks_json
    from sentinel.agent.selfcheck import run_selfcheck

    checks = run_selfcheck(settings)
    if as_json:
        print(checks_json(checks))
    else:
        for c in checks:
            print(f"[{'OK' if c.ok else 'FALHA':5}] {c.name} - {c.detail}")
    return EXIT_OK if checks and all(c.ok for c in checks) else EXIT_ERROR


def cmd_stop(settings: Settings, timeout: float = 20.0) -> int:
    from sentinel.agent.lifecycle import STOP_REQUEST_FILE

    if not settings.paths.database_file.exists():
        print("Banco de dados não encontrado; o agente nunca foi executado.")
        return EXIT_OK
    run = asyncio.run(_read_status(settings))["latest_run"]
    if run is None or run["state"] != "running":
        print("O agente não está em execução.")
        return EXIT_OK
    request = settings.paths.data_dir / STOP_REQUEST_FILE
    request.write_text(str(run["id"]), encoding="ascii")
    print(f"Parada solicitada à execução #{run['id']} (PID {run['pid']}). Aguardando…")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.5)
        latest = asyncio.run(_read_status(settings))["latest_run"]
        if latest is not None and latest["id"] == run["id"] and latest["state"] == "stopped":
            print(f"Agente encerrado ({_EXIT_LABELS.get(latest['exit_status'], latest['exit_status'])}).")
            return EXIT_OK
    request.unlink(missing_ok=True)
    print(f"O agente não encerrou em {timeout:.0f}s.", file=sys.stderr)
    return EXIT_ERROR


def cmd_dashboard(settings: Settings, open_browser: bool = True) -> int:
    if not settings.api.enabled:
        print("A API está desativada em settings.yaml (api.enabled: false).", file=sys.stderr)
        return EXIT_ERROR
    if not settings.paths.database_file.exists():
        print("Banco de dados não encontrado. Execute 'python -m sentinel init'.", file=sys.stderr)
        return EXIT_ERROR
    data = asyncio.run(_read_status(settings))
    run = data["latest_run"]
    if run is None or run["state"] != "running":
        print("O agente não está em execução. Inicie-o (tarefa agendada ou iniciar.bat) e tente novamente.", file=sys.stderr)
        return EXIT_ERROR

    code = asyncio.run(_create_login_code(settings))
    host = "127.0.0.1" if settings.api.host == "localhost" else settings.api.host
    host = f"[{host}]" if ":" in host else host
    url = f"http://{host}:{settings.api.port}/login?code={code}"
    print(f"Link de acesso (uso único, válido por {settings.api.login_code_seconds}s):")
    print(url)
    if open_browser and not webbrowser.open(url):
        print("Não foi possível abrir o navegador automaticamente; copie o link acima.")
    return EXIT_OK


async def _create_login_code(settings: Settings) -> str:
    db = Database(settings.paths.database_file, settings.database.busy_timeout_ms)
    await db.open()
    try:
        return await AuthRepository(db).create_login_code(settings.api.login_code_seconds)
    finally:
        await db.close()


_EXIT_LABELS = {
    "clean": "clean",
    "system_shutdown": "desligamento do Windows",
    "unclean": "encerramento inesperado",
    "failed": "falha",
    "interrupted": "interrompido",
}


def cmd_status(settings: Settings, as_json: bool = False) -> int:
    if not settings.paths.database_file.exists():
        if as_json:
            print(json.dumps({"initialized": False}))
        else:
            print("Banco de dados não encontrado. Execute 'python -m sentinel init'.")
        return EXIT_ERROR
    data = asyncio.run(_read_status(settings))
    if as_json:
        # ensure_ascii evita problemas de codificação no console do Windows.
        print(json.dumps(data, ensure_ascii=True))
        return EXIT_OK

    run = data["latest_run"]
    if run is None:
        print("Nenhuma execução do agente registrada.")
    else:
        age = run["heartbeat_age_seconds"]
        state = {
            "running": "em execução",
            "stopped": f"parado ({_EXIT_LABELS.get(run['exit_status'], run['exit_status'])}) em {run['stopped_at']}",
            "stale": f"sem sinal de vida há {age:.0f}s (possível encerramento inesperado)",
        }[run["state"]]
        print(f"Execução #{run['id']} — PID {run['pid']} — versão {run['version']}")
        print(f"  Estado          : {state}")
        print(f"  Iniciado em     : {run['started_at']}")
        print(f"  Último heartbeat: {run['last_heartbeat']} (há {age:.0f}s)")

    print("\nEventos recentes:")
    if not data["recent_events"]:
        print("  (nenhum)")
    for event in data["recent_events"]:
        print(f"  {event['timestamp']}  [{event['severity']:>8}]  {event['title']}")
        if event["description"]:
            print(f"      {event['description']}")
    return EXIT_OK


async def _read_status(settings: Settings) -> dict[str, Any]:
    db = Database(settings.paths.database_file, settings.database.busy_timeout_ms)
    await db.open()
    try:
        runs_repo = AgentRunRepository(db)
        run = await runs_repo.latest()
        previous = await runs_repo.previous()
        events_repo = EventRepository(db)
        recent = await events_repo.recent(10)
        unclean = await events_repo.count(EventType.AGENT_UNCLEAN_SHUTDOWN)
    finally:
        await db.close()

    if run is not None:
        age = (utc_now() - datetime.fromisoformat(run["last_heartbeat"])).total_seconds()
        run["heartbeat_age_seconds"] = round(age, 1)
        if run["stopped_at"]:
            run["state"] = "stopped"
        elif age <= settings.agent.heartbeat_interval_seconds * 2.5:
            run["state"] = "running"
        else:
            run["state"] = "stale"
    return {
        "initialized": True,
        "latest_run": run,
        "recent_events": recent,
        "unclean_shutdown_events": unclean,
        "previous_run": previous,
    }


def _fail(message: str, code: int, log_dir: Path) -> int:
    """Mostra o erro no console e também grava em arquivo — sob pythonw.exe não há console."""
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    error_log = log_dir / STARTUP_ERROR_FILE
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with error_log.open("a", encoding="utf-8") as fh:
            fh.write(f"{utc_now().isoformat()} [exit {code}] {message}\n")
            if sys.exc_info()[0] is not None:
                fh.write(traceback.format_exc())
    except OSError as exc:
        if sys.stderr is not None:
            print(f"(não foi possível gravar {error_log}: {exc})", file=sys.stderr)
    return code
