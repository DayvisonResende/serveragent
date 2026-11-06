"""Cadastro de servidores (PRD 6.2) e suas regras de validação.

Caminhos e argumentos vêm do usuário e são tratados como dados não confiáveis
(PRD 6.2): só um executável real, por caminho absoluto, sem shell e sem
interpretadores de comandos genéricos — senão "cadastrar servidor" viraria
"executar qualquer comando" (PRD 11.5).
"""

from __future__ import annotations

import ntpath
import os
import re
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator


class ServerState(StrEnum):
    """Estados do PRD 6.3."""

    ONLINE = "online"
    OFFLINE = "offline"
    STARTING = "starting"  # Inicializando
    RESTARTING = "restarting"  # Reiniciando
    DEGRADED = "degraded"  # Com problemas
    UNRESPONSIVE = "unresponsive"  # Sem resposta
    UNKNOWN = "unknown"  # Desconhecido
    DISABLED = "disabled"  # Desativado


BAD_STATES = frozenset({ServerState.OFFLINE, ServerState.DEGRADED, ServerState.UNRESPONSIVE})

Management = Literal["managed", "observed"]
Criticality = Literal["low", "medium", "high", "critical"]
ServerType = Literal["game", "node", "python", "database", "tunnel", "web", "service", "other"]

# Interpretadores de comandos e utilitários que executariam código arbitrário via argumentos.
FORBIDDEN_EXECUTABLES = frozenset(
    {
        "cmd.exe", "powershell.exe", "pwsh.exe", "powershell_ise.exe", "wscript.exe", "cscript.exe",
        "mshta.exe", "rundll32.exe", "regsvr32.exe", "msiexec.exe", "reg.exe", "schtasks.exe", "sc.exe",
        "wmic.exe", "bitsadmin.exe", "certutil.exe", "netsh.exe", "bash.exe", "wsl.exe",
        "sh", "bash", "zsh", "dash", "fish", "sudo", "su", "env", "xargs",
    }
)
ALLOWED_WINDOWS_EXTENSIONS = frozenset({".exe", ".com"})
SCRIPT_EXTENSIONS = frozenset({".bat", ".cmd"})
# Argumentos de scripts .bat/.cmd passam pelo cmd.exe: só caracteres que ele não interpreta.
_SAFE_SCRIPT_ARG = re.compile(r"^[\w.:\\/=+,@-]+$")
_UNSAFE_SCRIPT_PATH_CHARS = frozenset('%^&|<>!"\n\r')


def is_script(path: str | None) -> bool:
    return bool(path) and _suffix(path) in SCRIPT_EXTENSIONS


def _suffix(path: str) -> str:
    return ntpath.splitext(path)[1].lower() if ("\\" in path or ":" in path) else os.path.splitext(path)[1].lower()


def validate_script(path: str, arguments: list[str]) -> None:
    """Regras para .bat/.cmd: o cmd.exe interpreta & | < > ^ % ! — esses caracteres
    transformariam um argumento em um comando extra."""
    bad = sorted(set(path) & _UNSAFE_SCRIPT_PATH_CHARS)
    if bad:
        raise ValueError(f"o caminho do script contém caracteres não permitidos: {' '.join(bad)}")
    for arg in arguments:
        if not _SAFE_SCRIPT_ARG.match(arg):
            raise ValueError(
                f"argumento '{arg}' não permitido para scripts .bat/.cmd: use apenas letras, números e . _ - : \\ / = + , @ (sem espaços)"
            )
MAX_ARGS = 50
MAX_ARG_LENGTH = 1000


def _basename(path: str) -> str:
    return ntpath.basename(path).lower() if ("\\" in path or ":" in path) else os.path.basename(path).lower()


class HealthCheck(BaseModel):
    """Verificação de saúde (PRD 6.4). Sempre contra o próprio computador."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["none", "port", "tcp", "http"] = "none"
    path: str = "/"
    scheme: Literal["http", "https"] = "http"
    expected_status: int | None = Field(None, ge=100, le=599)  # None: qualquer status < 400
    timeout_seconds: float = Field(5, ge=0.5, le=30)

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        if not v.startswith("/") or any(c in v for c in "\r\n\x00 ") or len(v) > 300:
            raise ValueError("caminho HTTP deve começar com '/' e não conter espaços")
        return v


class ProcessMatch(BaseModel):
    """Como reconhecer o processo do servidor. Todos os critérios informados precisam bater."""

    model_config = ConfigDict(extra="forbid")

    exe_path: str | None = None
    name: str | None = None
    cmdline_contains: list[str] = Field(default_factory=list, max_length=10)
    port_owner: bool = False

    def is_empty(self) -> bool:
        return not (self.exe_path or self.name or self.cmdline_contains or self.port_owner)


class ServerSpec(BaseModel):
    """Dados de cadastro/alteração recebidos do dashboard ou da CLI."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    description: str = Field("", max_length=500)
    server_type: ServerType = "other"
    management: Management = "observed"
    executable: str | None = Field(None, max_length=500)
    arguments: list[str] = Field(default_factory=list)
    working_directory: str | None = Field(None, max_length=500)
    port: int | None = Field(None, ge=1, le=65_535)
    protocol: Literal["tcp", "udp", "http", "https"] = "tcp"
    health_check: HealthCheck = HealthCheck()
    process_match: ProcessMatch = ProcessMatch()
    log_path: str | None = Field(None, max_length=500)
    criticality: Criticality = "medium"
    startup_grace_seconds: int = Field(30, ge=3, le=600)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if any(ord(c) < 32 for c in v):
            raise ValueError("nome contém caracteres de controle")
        return v

    @field_validator("arguments")
    @classmethod
    def _arguments(cls, v: list[str]) -> list[str]:
        if len(v) > MAX_ARGS:
            raise ValueError(f"no máximo {MAX_ARGS} argumentos")
        for arg in v:
            if len(arg) > MAX_ARG_LENGTH or "\x00" in arg:
                raise ValueError("argumento inválido (longo demais ou com caractere nulo)")
        return v

    @model_validator(mode="after")
    def _consistency(self, info: ValidationInfo) -> ServerSpec:
        if self.executable is not None and self.executable == "":
            self.executable = None
        # Ao carregar do banco não exigimos que o arquivo ainda exista: um executável removido
        # não pode impedir a listagem — a falha aparece ao tentar iniciar.
        check_exists = not (info.context or {}).get("skip_exists", False)
        if self.management == "managed":
            if not self.executable:
                raise ValueError("servidor gerenciado precisa de um executável")
            validate_executable(self.executable, check_exists=check_exists)
            if is_script(self.executable):
                validate_script(self.executable, self.arguments)
            if self.working_directory and not Path(self.working_directory).is_absolute():
                raise ValueError("diretório de trabalho deve ser um caminho absoluto")
        if self.health_check.type in ("port", "tcp", "http") and self.port is None:
            raise ValueError("a verificação de saúde escolhida exige uma porta")
        if self.process_match.port_owner and self.port is None:
            raise ValueError("reconhecer o processo pela porta exige informar a porta")
        if self.process_match.is_empty() and not self.executable and self.port is None:
            raise ValueError("informe ao menos executável, nome de processo ou porta para reconhecer o servidor")
        return self

    def effective_match(self) -> ProcessMatch:
        """Critério efetivo: o informado ou um derivado do executável/argumentos/porta."""
        if not self.process_match.is_empty():
            return self.process_match
        if self.executable and is_script(self.executable):
            # O processo raiz é o cmd.exe que executa o script; a linha de comando contém o caminho dele.
            return ProcessMatch(name="cmd.exe", cmdline_contains=[self.executable])
        if self.executable:
            return ProcessMatch(exe_path=self.executable, cmdline_contains=[a for a in self.arguments if a][:10])
        return ProcessMatch(port_owner=True)


def validate_executable(path: str, check_exists: bool = True) -> None:
    """Valida o executável de um servidor gerenciado. Levanta ValueError com o motivo."""
    # Interpretadores primeiro: o motivo mais importante aparece mesmo com caminho inválido.
    name = _basename(path)
    if name in FORBIDDEN_EXECUTABLES:
        raise ValueError(f"'{name}' é um interpretador de comandos e não pode ser cadastrado como servidor")
    is_windows_path = "\\" in path or (len(path) > 1 and path[1] == ":")
    if not (Path(path).is_absolute() or (is_windows_path and ntpath.isabs(path))):
        raise ValueError("o executável deve ser informado por caminho absoluto")
    if not check_exists:
        return  # carregando do banco: regras de plataforma e existência valem ao cadastrar/iniciar
    suffix = _suffix(path)
    if suffix in SCRIPT_EXTENSIONS and sys.platform != "win32":
        raise ValueError("scripts .bat/.cmd só podem ser iniciados no Windows")
    if sys.platform == "win32" and suffix not in ALLOWED_WINDOWS_EXTENSIONS | SCRIPT_EXTENSIONS:
        raise ValueError("no Windows, informe um arquivo .exe, .bat ou .cmd")
    if not Path(path).is_file():
        raise ValueError(f"executável não encontrado: {path}")


class ServerRecord(ServerSpec):
    """Servidor cadastrado (com identificador e datas)."""

    id: int

    @property
    def is_script(self) -> bool:
        return is_script(self.executable)
    created_at: str
    updated_at: str

    def summary(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
