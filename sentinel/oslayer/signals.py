"""Tratamento de sinais de encerramento, por plataforma."""

from __future__ import annotations

import asyncio
import signal
import sys
from typing import Callable


def install_stop_handlers(loop: asyncio.AbstractEventLoop, on_stop: Callable[[], None]) -> None:
    """Chama ``on_stop`` no loop quando o processo recebe Ctrl+C / término.

    Observação: quando o Windows Task Scheduler encerra a tarefa ele usa
    TerminateProcess, que não envia sinal algum. Esse caso é detectado na
    próxima inicialização como "encerramento inesperado".
    """
    if sys.platform == "win32":
        # ProactorEventLoop não suporta add_signal_handler.
        def handler(signum: int, frame: object) -> None:
            loop.call_soon_threadsafe(on_stop)

        signal.signal(signal.SIGINT, handler)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, handler)
    else:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, on_stop)
