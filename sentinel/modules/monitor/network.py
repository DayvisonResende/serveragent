"""Coleta de rede (PRD 5.5). Apenas contadores e endereços — nenhum conteúdo de tráfego."""

from __future__ import annotations

import socket
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import psutil


@dataclass(frozen=True, slots=True)
class InterfaceSample:
    name: str
    is_up: bool
    is_loopback: bool
    speed_mbps: int | None
    ipv4: list[str]
    ipv6: list[str]
    bytes_sent: int
    bytes_recv: int
    upload_bps: float | None  # None = ainda sem medição anterior
    download_bps: float | None
    errors_in: int
    errors_out: int
    drops_in: int
    drops_out: int


@dataclass(frozen=True, slots=True)
class NetworkSample:
    upload_bps: float | None
    download_bps: float | None
    bytes_sent: int
    bytes_recv: int
    errors_in: int
    errors_out: int
    drops_in: int
    drops_out: int
    interfaces: list[InterfaceSample] = field(default_factory=list)

    def as_dict(self, include_interfaces: bool = True) -> dict[str, Any]:
        data = asdict(self)
        if not include_interfaces:
            data.pop("interfaces")
        return data


def _is_loopback(name: str, ipv4: list[str]) -> bool:
    lowered = name.lower()
    return lowered == "lo" or "loopback" in lowered or any(a.startswith("127.") for a in ipv4)


class NetworkCollector:
    """Taxas calculadas pela diferença de contadores entre duas coletas.

    Se um contador diminuir (adaptador reiniciado, estouro), a taxa daquela
    interface fica ``None`` nessa coleta em vez de exibir um valor falso.
    """

    # Endereços e estado das placas mudam raramente e são caros de ler no Windows
    # (GetAdaptersAddresses); os contadores de bytes são lidos a cada coleta.
    INTERFACE_INFO_TTL = 60.0

    def __init__(self) -> None:
        self._last: dict[str, tuple[int, int]] = {}
        self._last_time: float | None = None
        self._if_cache: tuple[float, dict, dict] | None = None

    def _interface_info(self, now: float) -> tuple[dict, dict]:
        if self._if_cache is None or now - self._if_cache[0] > self.INTERFACE_INFO_TTL:
            self._if_cache = (now, psutil.net_if_addrs(), psutil.net_if_stats())
        return self._if_cache[1], self._if_cache[2]

    def collect(self) -> NetworkSample:
        now = time.monotonic()
        counters = psutil.net_io_counters(pernic=True)
        addrs, stats = self._interface_info(now)
        if set(counters) - set(addrs):  # placa nova (ex.: VPN conectou): atualiza já
            self._if_cache = None
            addrs, stats = self._interface_info(now)
        elapsed = (now - self._last_time) if self._last_time is not None else None

        interfaces: list[InterfaceSample] = []
        for name, c in counters.items():
            ipv4 = [a.address for a in addrs.get(name, []) if a.family == socket.AF_INET]
            ipv6 = [a.address.split("%")[0] for a in addrs.get(name, []) if a.family == socket.AF_INET6]
            st = stats.get(name)
            up_bps = down_bps = None
            previous = self._last.get(name)
            if elapsed and elapsed > 0 and previous is not None:
                d_sent, d_recv = c.bytes_sent - previous[0], c.bytes_recv - previous[1]
                if d_sent >= 0 and d_recv >= 0:
                    up_bps, down_bps = d_sent / elapsed, d_recv / elapsed
            interfaces.append(
                InterfaceSample(
                    name=name,
                    is_up=bool(st.isup) if st else False,
                    is_loopback=_is_loopback(name, ipv4),
                    speed_mbps=(st.speed or None) if st else None,
                    ipv4=ipv4,
                    ipv6=ipv6,
                    bytes_sent=c.bytes_sent,
                    bytes_recv=c.bytes_recv,
                    upload_bps=up_bps,
                    download_bps=down_bps,
                    errors_in=c.errin,
                    errors_out=c.errout,
                    drops_in=c.dropin,
                    drops_out=c.dropout,
                )
            )
            self._last[name] = (c.bytes_sent, c.bytes_recv)
        self._last_time = now

        external = [i for i in interfaces if not i.is_loopback]
        rates_known = [i for i in external if i.upload_bps is not None]
        measured = bool(rates_known) and len(rates_known) == len(external)
        return NetworkSample(
            upload_bps=round(sum(i.upload_bps or 0 for i in external), 1) if measured else None,
            download_bps=round(sum(i.download_bps or 0 for i in external), 1) if measured else None,
            bytes_sent=sum(i.bytes_sent for i in external),
            bytes_recv=sum(i.bytes_recv for i in external),
            errors_in=sum(i.errors_in for i in external),
            errors_out=sum(i.errors_out for i in external),
            drops_in=sum(i.drops_in for i in external),
            drops_out=sum(i.drops_out for i in external),
            interfaces=interfaces,
        )
