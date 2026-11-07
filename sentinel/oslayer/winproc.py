"""Lista de processos do Windows numa única chamada (como o Gerenciador de Tarefas).

``psutil`` lê cada atributo de cada processo separadamente; para processos do
sistema (acesso negado) ele recorre a uma varredura completa da lista a cada
atributo — no i3 isso custava ~850 ms por coleta. ``NtQuerySystemInformation``
(SystemProcessInformation) devolve PID, pai, nome, horário de criação, tempos de
CPU e memória de TODOS os processos de uma vez, sem precisar abrir nenhum.

O formato da estrutura é o de 64 bits (offsets documentados abaixo). ``parse``
é puro e testável fora do Windows; ``snapshot`` só funciona no Windows.
"""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass

SYSTEM_PROCESS_INFORMATION = 5
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
_EPOCH_AS_FILETIME = 116444736000000000  # 1970-01-01 em intervalos de 100 ns desde 1601

# Offsets de SYSTEM_PROCESS_INFORMATION (x64)
OFF_NEXT = 0x00            # ULONG NextEntryOffset
OFF_CREATE = 0x20          # LARGE_INTEGER CreateTime
OFF_USER = 0x28            # LARGE_INTEGER UserTime
OFF_KERNEL = 0x30          # LARGE_INTEGER KernelTime
OFF_NAME_LEN = 0x38        # UNICODE_STRING.Length (bytes)
OFF_NAME_BUF = 0x40        # UNICODE_STRING.Buffer (ponteiro)
OFF_PID = 0x50             # HANDLE UniqueProcessId
OFF_PPID = 0x58            # HANDLE InheritedFromUniqueProcessId
OFF_WORKING_SET = 0x90     # SIZE_T WorkingSetSize  (= rss do psutil)
MIN_ENTRY = OFF_WORKING_SET + 8


@dataclass(frozen=True, slots=True)
class RawProcess:
    pid: int
    ppid: int
    name: str
    create_time: float | None  # epoch (s); None para processos sem horário (Idle/System)
    cpu_seconds: float         # usuário + kernel
    rss: int


def filetime_to_epoch(value: int) -> float | None:
    if value <= _EPOCH_AS_FILETIME:
        return None
    return (value - _EPOCH_AS_FILETIME) / 10_000_000


def parse(buffer: bytes, base_address: int, read_name) -> list[RawProcess]:
    """Percorre a lista encadeada. ``read_name(endereço, bytes)`` lê o nome (UTF-16)."""
    out: list[RawProcess] = []
    offset = 0
    seen = 0
    while True:
        if offset + MIN_ENTRY > len(buffer):
            raise ValueError("estrutura de processos truncada")
        next_entry = struct.unpack_from("<I", buffer, offset + OFF_NEXT)[0]
        create, user, kernel = struct.unpack_from("<qqq", buffer, offset + OFF_CREATE)
        name_len = struct.unpack_from("<H", buffer, offset + OFF_NAME_LEN)[0]
        name_ptr = struct.unpack_from("<Q", buffer, offset + OFF_NAME_BUF)[0]
        pid, ppid = struct.unpack_from("<QQ", buffer, offset + OFF_PID)
        rss = struct.unpack_from("<Q", buffer, offset + OFF_WORKING_SET)[0]
        name = read_name(name_ptr, name_len) if name_ptr and name_len else ("System Idle Process" if pid == 0 else "")
        out.append(RawProcess(int(pid), int(ppid), name, filetime_to_epoch(create), (user + kernel) / 10_000_000, int(rss)))
        seen += 1
        if next_entry == 0 or seen > 100_000:
            break
        offset += next_entry
    return out


def snapshot() -> list[RawProcess]:
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise OSError("disponível apenas no Windows 64 bits")
    import ctypes
    from ctypes import wintypes

    ntdll = ctypes.WinDLL("ntdll")
    query = ntdll.NtQuerySystemInformation
    query.argtypes = [wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
    query.restype = ctypes.c_long

    size = 512 * 1024
    for _ in range(8):  # a lista pode crescer entre chamadas: aumenta o buffer e tenta de novo
        buf = ctypes.create_string_buffer(size)
        needed = wintypes.ULONG(0)
        status = query(SYSTEM_PROCESS_INFORMATION, buf, size, ctypes.byref(needed)) & 0xFFFFFFFF
        if status == STATUS_INFO_LENGTH_MISMATCH:
            size = max(size * 2, needed.value + 64 * 1024)
            continue
        if status != 0:
            raise OSError(f"NtQuerySystemInformation falhou: 0x{status:08X}")
        base = ctypes.addressof(buf)
        raw = bytes(buf)  # cópia para leitura estruturada

        def read_name(address: int, length: int) -> str:
            start = address - base
            if 0 <= start <= len(raw) - length:
                return raw[start:start + length].decode("utf-16-le", errors="replace")
            return ctypes.wstring_at(address, length // 2)

        return parse(raw, base, read_name)
    raise OSError("lista de processos mudou rápido demais")
