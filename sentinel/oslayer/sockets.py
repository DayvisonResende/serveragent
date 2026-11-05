"""Abertura do socket de escuta da API, com as opções corretas por plataforma."""

from __future__ import annotations

import socket
import sys


def bind_listener(host: str, port: int) -> socket.socket:
    """Abre um socket TCP em ``host:port``. Levanta ``OSError`` se a porta estiver ocupada.

    No Windows usa SO_EXCLUSIVEADDRUSE: sem ele, outro programa poderia se
    associar à mesma porta e interceptar conexões. Em POSIX usa SO_REUSEADDR
    apenas para permitir reinício rápido (conexões em TIME_WAIT).
    """
    address = "127.0.0.1" if host == "localhost" else host
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        if sys.platform == "win32":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)  # type: ignore[attr-defined]
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((address, port))
        sock.listen(128)
        sock.setblocking(False)
    except OSError:
        sock.close()
        raise
    return sock
