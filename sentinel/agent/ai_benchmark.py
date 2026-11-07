"""Teste de viabilidade da IA local (Fase 5, PRD 9.2): qual modelo cabe no computador.

Para cada candidato: baixa (se autorizado), mede carga, velocidade de geração,
memória, se escolhe a ferramenta certa em perguntas reais do Sentinel (e se NÃO
chama ferramenta quando não precisa) e a qualidade da resposta em português.
Nenhuma ferramenta é executada: os dados entregues ao modelo são fictícios e
marcados como tal.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import psutil

from sentinel.modules.ai.model_profile import options_for, strip_thinking, think_flag
from sentinel.modules.ai.ollama import ChatResult, OllamaClient, OllamaError

# LFM3-1.7B é o modelo previsto no PRD (docs.liquid.ai/lfm/models/lfm3-1.7b); os demais servem de comparação.
CANDIDATES: list[tuple[str, str]] = [
    ("LFM3 1.7B (Liquid AI)", "hf.co/LiquidAI/LFM3-1.7B-GGUF:Q4_K_M"),
    ("Qwen3 1.7B", "qwen3:1.7b"),
    ("Llama 3.2 3B", "llama3.2:3b"),
]

SYSTEM = (
    "Você é o Sentinel, assistente que administra este computador e seus servidores. "
    "Responda sempre em português do Brasil, de forma curta. Para qualquer dado do computador "
    "use as ferramentas; nunca invente números. Se a pergunta não precisa de dados, responda direto."
)

TOOLS = [
    {"type": "function", "function": {"name": "get_system_status", "description": "Estado geral do computador: CPU, memória, disco, rede.",
                                      "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_server_status", "description": "Estado de um servidor cadastrado (online/offline, CPU, memória).",
                                      "parameters": {"type": "object", "properties": {"server_name": {"type": "string", "description": "Nome do servidor"}},
                                                     "required": ["server_name"]}}},
    {"type": "function", "function": {"name": "get_disk_usage", "description": "Espaço total, usado e livre de cada disco.",
                                      "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_process_list", "description": "Processos em execução, ordenados.",
                                      "parameters": {"type": "object", "properties": {"sort_by": {"type": "string", "enum": ["cpu", "memory"]}},
                                                     "required": ["sort_by"]}}},
]


@dataclass
class ToolCase:
    question: str
    expected: str | None  # None: não deve chamar ferramenta
    check_args: Callable[[dict[str, Any]], bool] = lambda args: True


CASES = [
    ToolCase("Como está meu servidor MossBlade?", "get_server_status",
             lambda a: "mossblade" in str(a.get("server_name", "")).lower().replace(" ", "")),
    ToolCase("Qual processo está consumindo mais CPU agora?", "get_process_list", lambda a: a.get("sort_by") == "cpu"),
    ToolCase("Quanto espaço livre eu tenho no disco?", "get_disk_usage"),
    ToolCase("Oi! Tudo bem? O que você consegue fazer?", None),
]


@dataclass
class ModelReport:
    label: str
    model: str
    available: bool = False
    error: str | None = None
    download_seconds: float | None = None
    size_bytes: int | None = None
    load_seconds: float | None = None
    output_tps: float | None = None
    prompt_tps: float | None = None
    memory_bytes: int | None = None
    tool_results: list[tuple[str, bool, str]] = field(default_factory=list)
    answer_sample: str = ""
    answer_seconds: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def tool_score(self) -> int:
        return sum(ok for _, ok, _ in self.tool_results)


_think_flag = think_flag
_options = options_for


class _Chat:
    """Chama o modelo; se o Ollama não aceitar desligar o raciocínio, segue com ele ligado e anota."""

    def __init__(self, client: OllamaClient, model: str, report: "ModelReport") -> None:
        self.client, self.model, self.report = client, model, report
        self.think = _think_flag(model)

    def __call__(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, num_predict: int = 200) -> ChatResult:
        try:
            return self.client.chat(self.model, messages, tools=tools, options=_options(self.model, {"num_predict": num_predict}), think=self.think)
        except OllamaError as exc:
            if self.think is not None and "think" in str(exc).lower():
                self.think = None
                self.report.notes.append("o Ollama não aceitou desligar o raciocínio deste modelo")
                return self.client.chat(self.model, messages, tools=tools, options=_options(self.model, {"num_predict": num_predict}))
            raise


def run(client: OllamaClient, pull: bool, models: list[tuple[str, str]], log: Callable[[str], None]) -> list[ModelReport]:
    reports = []
    for label, model in models:
        report = ModelReport(label, model)
        reports.append(report)
        log(f"\n=== {label} ({model}) ===")
        try:
            if not client.has_model(model):
                if not pull:
                    report.error = "não baixado (rode com permissão para baixar)"
                    log(f"  {report.error}")
                    continue
                log("  Baixando… (pode levar alguns minutos)")
                started = time.monotonic()
                last = [0.0]

                def progress(status: str, fraction: float | None) -> None:
                    if fraction is not None and fraction - last[0] >= 0.1:
                        last[0] = fraction
                        log(f"  {status} {fraction:.0%}")

                client.pull(model, progress)
                report.download_seconds = round(time.monotonic() - started, 1)
            report.available = True
            report.size_bytes = next((m.get("size") for m in client.models() if m.get("name", "").startswith(model.split(":")[0])), None)
            _measure(client, report, log)
        except OllamaError as exc:
            report.error = str(exc)
            log(f"  ERRO: {exc}")
        finally:
            try:
                client.unload(model)
            except OllamaError:
                pass
    return reports


def _measure(client: OllamaClient, report: ModelReport, log: Callable[[str], None]) -> None:
    model = report.model
    chat = _Chat(client, model, report)
    log("  Carregando e medindo velocidade…")
    warm = chat([{"role": "system", "content": SYSTEM},
                 {"role": "user", "content": "Explique em três frases o que é o uso de CPU de um computador."}], num_predict=160)
    report.load_seconds = round(warm.load_seconds, 1)
    report.output_tps = round(warm.output_tokens_per_second or 0, 1)
    report.prompt_tps = round(warm.prompt_tokens_per_second or 0, 1)
    loaded = next((m for m in client.loaded() if m.get("name", "").startswith(model.split(":")[0]) or m.get("model") == model), None)
    report.memory_bytes = loaded.get("size") if loaded else None
    log(f"  carga {report.load_seconds}s · geração {report.output_tps} tokens/s · leitura {report.prompt_tps} tokens/s")

    for case in CASES:
        result = chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": case.question}], tools=TOOLS)
        ok, detail = _grade(case, result)
        report.tool_results.append((case.question, ok, detail))
        log(f"  [{'OK' if ok else 'ERRO'}] {case.question} → {detail}")

    # Resposta final com dados de ferramenta (fictícios, como teste): qualidade do português.
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "Quanto espaço livre eu tenho no disco?"},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "get_disk_usage", "arguments": {}}}]},
        {"role": "tool", "content": json.dumps({"discos": [{"unidade": "C:", "total_gb": 118.6, "livre_gb": 23.1, "uso_percent": 80.5}]})},
    ]
    final = chat(messages, tools=TOOLS, num_predict=160)
    text = _strip_thinking(final.content)
    if text != (final.content or "").strip():
        report.notes.append("o raciocínio apareceu misturado ao texto da resposta")
    report.answer_sample = (text or "(sem texto)")[:400]
    report.answer_seconds = round(final.total_seconds, 1)
    log(f"  Resposta ({report.answer_seconds}s): {report.answer_sample}")


_strip_thinking = strip_thinking


def _grade(case: ToolCase, result: ChatResult) -> tuple[bool, str]:
    calls = result.tool_calls
    if case.expected is None:
        if calls:
            return False, f"chamou {calls[0].get('name')} sem necessidade"
        return bool(_strip_thinking(result.content)), f"respondeu direto ({result.total_seconds:.1f}s)"
    if not calls:
        text = result.content.strip().replace("\n", " ")[:80]
        return False, f"não chamou ferramenta (texto: {text!r})"
    call = calls[0]
    args = call.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    name_ok = call.get("name") == case.expected
    args_ok = name_ok and case.check_args(args)
    return name_ok and args_ok, f"{call.get('name')}({json.dumps(args, ensure_ascii=False)}) em {result.total_seconds:.1f}s"


def summarize(reports: list[ModelReport]) -> list[str]:
    lines = ["", "== Resumo ==", f"{'Modelo':<26}{'Geração':>12}{'Carga':>9}{'Memória':>10}{'Ferramentas':>13}"]
    for r in reports:
        if not r.available or r.output_tps is None:
            lines.append(f"{r.label:<26}  indisponível: {r.error}")
            continue
        mem = f"{r.memory_bytes / 1024**3:.1f} GB" if r.memory_bytes else "?"
        lines.append(f"{r.label:<26}{r.output_tps:>8} t/s{r.load_seconds:>8}s{mem:>10}{r.tool_score:>9}/{len(CASES)}")
        for note in r.notes:
            lines.append(f"{'':<26}obs.: {note}")
    usable = [r for r in reports if r.available and r.output_tps and r.output_tps >= 4 and r.tool_score >= len(CASES) - 1]
    if usable:
        best = max(usable, key=lambda r: (r.tool_score, r.output_tps or 0))
        lines.append(f"\nRecomendação: {best.label} ({best.model}) — {best.tool_score}/{len(CASES)} nas ferramentas, {best.output_tps} tokens/s.")
    else:
        lines.append("\nNenhum candidato atingiu o mínimo (≥ 4 tokens/s e no máximo 1 erro nas ferramentas).")
    vm = psutil.virtual_memory()
    lines.append(f"Memória livre do computador agora: {vm.available / 1024**3:.1f} GB de {vm.total / 1024**3:.1f} GB.")
    return lines
