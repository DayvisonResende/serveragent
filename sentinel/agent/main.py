"""Linha de comando do Sentinel.

    python -m sentinel init          prepara configuração, diretórios e banco
    python -m sentinel run           executa o agente em primeiro plano
    python -m sentinel status        mostra a última execução e eventos recentes
    python -m sentinel check-config  valida e exibe a configuração efetiva
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path

from sentinel import __version__
from sentinel.agent import bootstrap
from sentinel.agent.config import PROJECT_ROOT, Settings, load_settings, resolve_config_path
from sentinel.agent.lifecycle import Agent
from sentinel.agent.logging_setup import configure_logging
from sentinel.core.clock import utc_now
from sentinel.core.exceptions import ConfigurationError, DatabaseError, InstanceLockError, SentinelError
from sentinel.database.database import Database
from sentinel.database.repositories import AgentRunRepository, EventRepository
from sentinel.oslayer.info import get_platform_info
from sentinel.oslayer.instance_lock import InstanceLock
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
    commands.add_parser("status", help="mostra a última execução e os eventos recentes")
    commands.add_parser("check-config", help="valida e exibe a configuração efetiva")
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
            return cmd_status(settings)
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


async def _run_agent(settings: Settings) -> None:
    stop = asyncio.Event()
    install_stop_handlers(asyncio.get_running_loop(), stop.set)
    agent = Agent(settings)
    await agent.run(stop)


def cmd_status(settings: Settings) -> int:
    if not settings.paths.database_file.exists():
        print("Banco de dados não encontrado. Execute 'python -m sentinel init'.")
        return EXIT_ERROR
    latest, events = asyncio.run(_read_status(settings))

    if latest is None:
        print("Nenhuma execução do agente registrada.")
    else:
        heartbeat_age = (utc_now() - datetime.fromisoformat(latest["last_heartbeat"])).total_seconds()
        if latest["stopped_at"]:
            state = f"parado ({latest['exit_status']}) em {latest['stopped_at']}"
        elif heartbeat_age <= settings.agent.heartbeat_interval_seconds * 2.5:
            state = "em execução"
        else:
            state = f"sem sinal de vida há {heartbeat_age:.0f}s (possível encerramento inesperado)"
        print(f"Execução #{latest['id']} — PID {latest['pid']} — versão {latest['version']}")
        print(f"  Estado          : {state}")
        print(f"  Iniciado em     : {latest['started_at']}")
        print(f"  Último heartbeat: {latest['last_heartbeat']} (há {heartbeat_age:.0f}s)")

    print("\nEventos recentes:")
    if not events:
        print("  (nenhum)")
    for event in events:
        print(f"  {event['timestamp']}  [{event['severity']:>8}]  {event['title']}")
        if event["description"]:
            print(f"      {event['description']}")
    return EXIT_OK


async def _read_status(settings: Settings) -> tuple[dict | None, list[dict]]:
    db = Database(settings.paths.database_file, settings.database.busy_timeout_ms)
    await db.open()
    try:
        return await AgentRunRepository(db).latest(), await EventRepository(db).recent(10)
    finally:
        await db.close()


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
