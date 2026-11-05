"""Detecção de desligamento/logoff do Windows.

Sob ``pythonw.exe`` não há console, então o Windows não envia sinais: ele
avisa o encerramento da sessão com ``WM_QUERYENDSESSION``/``WM_ENDSESSION``
apenas para janelas de nível superior. Criamos uma janela invisível (não
"message-only", que não recebe broadcasts) numa thread própria.

Ao receber ``WM_ENDSESSION`` pedimos o encerramento limpo do agente e
seguramos a resposta até ele terminar (com limite), porque o Windows pode
matar o processo assim que o handler retornar.

Em outros sistemas este módulo não faz nada (``start()`` retorna False).
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import Callable

log = logging.getLogger(__name__)

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
ENDSESSION_LOGOFF = 0x80000000

# O Windows concede poucos segundos após WM_ENDSESSION.
DEFAULT_SHUTDOWN_WAIT_SECONDS = 4.5

OnSessionEnd = Callable[[str], None]  # recebe "shutdown" ou "logoff"
WaitDone = Callable[[float], bool]  # aguarda o fim do encerramento; True se concluído


class ShutdownListener:
    def __init__(
        self,
        on_session_end: OnSessionEnd,
        wait_done: WaitDone,
        wait_seconds: float = DEFAULT_SHUTDOWN_WAIT_SECONDS,
    ) -> None:
        self._on_session_end = on_session_end
        self._wait_done = wait_done
        self._wait_seconds = wait_seconds
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._hwnd: int | None = None
        self._win32: _Win32 | None = None
        self.session_ended: str | None = None

    def start(self) -> bool:
        if sys.platform != "win32":
            return False
        self._win32 = _Win32()
        self._thread = threading.Thread(target=self._run, name="sentinel-shutdown-listener", daemon=True)
        self._thread.start()
        self._ready.wait(5)
        if self._hwnd is None:
            log.error("Não foi possível criar a janela de detecção de desligamento")
            return False
        log.info("Detecção de desligamento do Windows ativa")
        return True

    def stop(self) -> None:
        if self._thread is None or self._win32 is None:
            return
        if self._hwnd is not None:
            self._win32.post_message(self._hwnd, WM_CLOSE)
        self._thread.join(timeout=5)
        self._thread = None

    def handle_message(self, msg: int, wparam: int, lparam: int) -> int | None:
        """Lógica da janela, independente de ctypes (testável). None = tratamento padrão."""
        if msg == WM_QUERYENDSESSION:
            return 1  # não bloqueamos o desligamento
        if msg == WM_ENDSESSION:
            if wparam:  # a sessão realmente vai terminar
                kind = "logoff" if lparam & ENDSESSION_LOGOFF else "shutdown"
                self.session_ended = kind
                log.info("Windows encerrando a sessão; finalizando o Sentinel", extra={"kind": kind})
                self._on_session_end(kind)
                if not self._wait_done(self._wait_seconds):
                    log.warning("Encerramento não concluído antes do limite do Windows")
            return 0
        return None

    def _run(self) -> None:
        assert self._win32 is not None
        try:
            self._hwnd = self._win32.create_window(self._wndproc)
        except OSError:
            log.exception("Falha ao criar janela oculta")
        finally:
            self._ready.set()
        if self._hwnd is not None:
            self._win32.message_loop()

    def _wndproc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        assert self._win32 is not None
        try:
            result = self.handle_message(msg, wparam, lparam)
            if result is not None:
                return result
            if msg == WM_CLOSE:
                self._win32.destroy_window(hwnd)
                return 0
            if msg == WM_DESTROY:
                self._win32.post_quit()
                return 0
        except Exception:
            # Exceções dentro de callbacks ctypes seriam apenas impressas; registramos explicitamente.
            log.exception("Erro no tratamento de mensagem do Windows", extra={"msg": msg})
        return self._win32.default_proc(hwnd, msg, wparam, lparam)


class _Win32:
    """Chamadas mínimas à API Win32 via ctypes, com assinaturas explícitas (64 bits)."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        lresult = wintypes.LPARAM
        self.WNDPROC = ctypes.WINFUNCTYPE(lresult, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", self.WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        self.WNDCLASSW = WNDCLASSW
        self.MSG = wintypes.MSG

        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = lresult
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.TranslateMessage.restype = wintypes.BOOL
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = lresult
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostMessageW.restype = wintypes.BOOL
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        user32.PostQuitMessage.restype = None
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        self._user32 = user32
        self._kernel32 = kernel32
        self._callback = None  # referência mantida: se for coletado, o Windows chamaria memória liberada

    def create_window(self, wndproc: Callable[[int, int, int, int], int]) -> int:
        import os

        ctypes = self._ctypes
        self._callback = self.WNDPROC(wndproc)
        instance = self._kernel32.GetModuleHandleW(None)
        class_name = f"SentinelShutdownListener{os.getpid()}"
        wc = self.WNDCLASSW()
        wc.lpfnWndProc = self._callback
        wc.hInstance = instance
        wc.lpszClassName = class_name
        if not self._user32.RegisterClassW(ctypes.byref(wc)):
            raise ctypes.WinError(ctypes.get_last_error())
        hwnd = self._user32.CreateWindowExW(0, class_name, "Sentinel", 0, 0, 0, 0, 0, None, None, instance, None)
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        return hwnd

    def message_loop(self) -> None:
        ctypes = self._ctypes
        msg = self.MSG()
        while True:
            result = self._user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result == 0:  # WM_QUIT
                return
            if result == -1:
                log.error("GetMessageW falhou", extra={"error": ctypes.get_last_error()})
                return
            self._user32.TranslateMessage(ctypes.byref(msg))
            self._user32.DispatchMessageW(ctypes.byref(msg))

    def post_message(self, hwnd: int, msg: int) -> None:
        self._user32.PostMessageW(hwnd, msg, 0, 0)

    def destroy_window(self, hwnd: int) -> None:
        self._user32.DestroyWindow(hwnd)

    def post_quit(self) -> None:
        self._user32.PostQuitMessage(0)

    def default_proc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        return self._user32.DefWindowProcW(hwnd, msg, wparam, lparam)
