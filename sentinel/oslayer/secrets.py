"""Proteção de segredos em repouso (PRD 17.5: tokens nunca em texto puro).

Windows: DPAPI (CryptProtectData) no escopo do usuário — só a mesma conta do
Windows, nesta máquina, consegue decifrar. Não protege contra um programa
malicioso rodando como o próprio usuário; protege contra cópia do banco para
outro lugar e contra leitura por outras contas.

Fora do Windows (desenvolvimento) não há proteção: o valor é guardado como está
e marcado como ``none``, o que a API informa ao usuário.
"""

from __future__ import annotations

import sys

ENTROPY = b"sentinel-secrets-v1"


def protect(value: bytes) -> tuple[str, bytes]:
    if sys.platform == "win32":
        return "dpapi", _dpapi(value, encrypt=True)
    return "none", value


def unprotect(protection: str, data: bytes) -> bytes:
    if protection == "dpapi":
        if sys.platform != "win32":
            raise OSError("Segredo protegido com DPAPI só pode ser lido no Windows")
        return _dpapi(data, encrypt=False)
    if protection == "none":
        return data
    raise ValueError(f"Proteção desconhecida: {protection}")


def _dpapi(data: bytes, encrypt: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(raw: bytes) -> tuple[DATA_BLOB, ctypes.Array[ctypes.c_char]]:
        buffer = ctypes.create_string_buffer(raw, len(raw))
        return DATA_BLOB(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    func = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    func.argtypes = [
        ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR if encrypt else ctypes.c_void_p, ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
    ]
    func.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    data_in, _keep = blob(data)
    entropy, _keep_entropy = blob(ENTROPY)
    data_out = DATA_BLOB()
    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    ok = func(ctypes.byref(data_in), None, ctypes.byref(entropy), None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(data_out))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(data_out.pbData, data_out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(data_out.pbData, ctypes.c_void_p))
