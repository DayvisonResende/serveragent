"""Cliente mínimo da API do Ollama (PRD 9.2/9.6). Somente no próprio computador.

Usa http.client (sem dependências novas). As chamadas são bloqueantes; o agente
as executa em threads. Nenhuma resposta do modelo é executada: o texto e as
"chamadas de ferramenta" sugeridas são apenas dados (PRD 9.7).
"""

from __future__ import annotations

import http.client
import json
from dataclasses import dataclass
from typing import Any, Callable, Iterator
from urllib.parse import urlparse

DEFAULT_URL = "http://127.0.0.1:11434"
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


class OllamaError(Exception):
    """Ollama indisponível ou erro de uma chamada (mensagem legível)."""


class OllamaUnavailable(OllamaError):
    """Ollama não está rodando ou não aceita conexões."""


@dataclass(frozen=True)
class ChatResult:
    content: str
    tool_calls: list[dict[str, Any]]
    thinking: str
    total_seconds: float
    load_seconds: float
    prompt_tokens: int
    prompt_seconds: float
    output_tokens: int
    output_seconds: float

    @property
    def output_tokens_per_second(self) -> float | None:
        return self.output_tokens / self.output_seconds if self.output_seconds > 0 else None

    @property
    def prompt_tokens_per_second(self) -> float | None:
        return self.prompt_tokens / self.prompt_seconds if self.prompt_seconds > 0 else None


class OllamaClient:
    def __init__(self, base_url: str = DEFAULT_URL, timeout: float = 300.0) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in LOOPBACK:
            raise ValueError("O Ollama deve estar no próprio computador (http://127.0.0.1:11434)")
        self.host = parsed.hostname
        self.port = parsed.port or 11434
        self.timeout = timeout

    # ------------------------------------------------------------- consultas

    def version(self) -> str:
        return str(self._request("GET", "/api/version").get("version", "?"))

    def models(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/tags").get("models", [])

    def loaded(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/ps").get("models", [])

    def has_model(self, name: str) -> bool:
        wanted = name if ":" in name.split("/")[-1] else f"{name}:latest"
        return any(m.get("name") in (name, wanted) or m.get("model") in (name, wanted) for m in self.models())

    # -------------------------------------------------------------- operações

    def pull(self, name: str, progress: Callable[[str, float | None], None] | None = None) -> None:
        """Baixa um modelo (pode levar minutos). ``progress(status, fração)``."""
        for event in self._stream("POST", "/api/pull", {"model": name, "stream": True}):
            if "error" in event:
                raise OllamaError(f"Falha ao baixar '{name}': {event['error']}")
            if progress:
                total, done = event.get("total"), event.get("completed")
                progress(event.get("status", ""), (done / total) if total and done is not None else None)

    def load(self, name: str, keep_alive: str = "5m") -> None:
        """Carrega o modelo na memória sem gerar nada (requisição sem prompt)."""
        self._request("POST", "/api/generate", {"model": name, "keep_alive": keep_alive})

    def unload(self, name: str) -> None:
        self._request("POST", "/api/generate", {"model": name, "keep_alive": 0})

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
        keep_alive: str | int = "5m",
        think: bool | None = None,
    ) -> ChatResult:
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": False, "keep_alive": keep_alive,
                                "options": {"temperature": 0, **(options or {})}}
        if tools:
            body["tools"] = tools
        if think is not None:
            body["think"] = think
        data = self._request("POST", "/api/chat", body)
        msg = data.get("message") or {}
        ns = 1e9
        return ChatResult(
            content=msg.get("content") or "",
            tool_calls=[c.get("function", c) for c in (msg.get("tool_calls") or [])],
            thinking=msg.get("thinking") or "",
            total_seconds=data.get("total_duration", 0) / ns,
            load_seconds=data.get("load_duration", 0) / ns,
            prompt_tokens=data.get("prompt_eval_count", 0),
            prompt_seconds=data.get("prompt_eval_duration", 0) / ns,
            output_tokens=data.get("eval_count", 0),
            output_seconds=data.get("eval_duration", 0) / ns,
        )

    # ----------------------------------------------------------------- HTTP

    def _connection(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        conn = self._connection()
        try:
            conn.request(method, path, body=json.dumps(body) if body is not None else None,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            raw = resp.read()
        except (ConnectionRefusedError, OSError) as exc:
            raise OllamaUnavailable(f"Ollama não está respondendo em {self.host}:{self.port} ({type(exc).__name__})") from exc
        finally:
            conn.close()
        try:
            data = json.loads(raw) if raw else {}
        except ValueError as exc:
            raise OllamaError(f"Resposta inválida do Ollama ({resp.status})") from exc
        if resp.status >= 400:
            raise OllamaError(str(data.get("error") or f"HTTP {resp.status}"))
        return data

    def _stream(self, method: str, path: str, body: dict[str, Any]) -> Iterator[dict[str, Any]]:
        conn = self._connection()
        try:
            conn.request(method, path, body=json.dumps(body), headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            if resp.status >= 400:
                raw = resp.read()
                try:
                    message = json.loads(raw).get("error")
                except ValueError:
                    message = None
                raise OllamaError(message or f"HTTP {resp.status}")
            buffer = b""
            while chunk := resp.read1(65536) if hasattr(resp, "read1") else resp.read(65536):
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line.strip():
                        yield json.loads(line)
        except (ConnectionRefusedError, OSError) as exc:
            raise OllamaUnavailable(f"Ollama não está respondendo em {self.host}:{self.port} ({type(exc).__name__})") from exc
        finally:
            conn.close()
