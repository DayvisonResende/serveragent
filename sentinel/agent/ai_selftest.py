"""Autoteste da IA local (etapa 9 do verificar.bat).

Roda depois da medição de consumo do agente: uma resposta do modelo ocupa a CPU
por dezenas de segundos e estragaria aquela medição.

Faz uma pergunta real pelo mesmo caminho do dashboard (API → assistente →
ferramentas → Ollama), numa conversa nova a cada execução: com o histórico de
uma execução anterior, o modelo poderia repetir a resposta antiga em vez de
consultar os dados (aconteceu no OptiPlex). A pergunta só lê dados: nada é pedido ou executado.
"""

from __future__ import annotations

import time

from sentinel.agent.client import ApiError, LocalClient
from sentinel.agent.config import Settings
from sentinel.agent.selfcheck import Check
from sentinel.modules.ai.ollama import OllamaClient, OllamaError

QUESTION = "Quantos servidores estão cadastrados e em que estado cada um está?"


def run(settings: Settings) -> list[Check]:
    checks: list[Check] = []
    ai = settings.ai
    http = LocalClient(settings, timeout=ai.timeout_seconds * (ai.max_tool_rounds + 1) + 30)
    try:
        status = http.request("GET", "/api/v1/ai/status?refresh=true")
    except (ApiError, OSError) as exc:
        return [Check("IA local disponível", False, f"agente não respondeu: {exc}")]
    checks.append(Check("IA local disponível", bool(status.get("available")),
                        f"{status.get('message')} · modelo {status.get('model') or 'nenhum'}"))
    if not status.get("available"):
        return checks

    # Como ao abrir a página Assistente: prepara o modelo; a pergunta seguinte aproveita.
    try:
        warm = http.request("POST", "/api/v1/ai/warmup")
        checks.append(Check("Aquecimento da IA (informativo)", True,
                            f"{warm['segundos']:.0f} s para carregar o modelo na memória" if warm.get("aquecido")
                            else "modelo já estava preparado"))
    except (ApiError, OSError) as exc:
        checks.append(Check("Aquecimento da IA", False, f"{type(exc).__name__}: {exc}"))

    started = time.monotonic()
    try:
        answer = http.request("POST", "/api/v1/chat", {"message": QUESTION, "conversation_id": f"autoteste-{int(time.time())}"})
    except (ApiError, OSError) as exc:
        checks.append(Check("Chat com a IA (pergunta real)", False, f"{type(exc).__name__}: {exc}"))
        return checks
    elapsed = time.monotonic() - started
    text = " ".join(str(answer.get("answer", "")).split())
    read_s, write_s = answer.get("tempo_leitura", 0), answer.get("tempo_escrita", 0)
    other = max(elapsed - read_s - write_s, 0)
    checks.append(Check("Chat com a IA (pergunta real)", bool(text),
                        f"{elapsed:.0f} s ({answer.get('rodadas', '?')} rodada(s): leitura {read_s:.0f} s de "
                        f"{answer.get('tokens_lidos', 0)} tokens, escrita {write_s:.0f} s de {answer.get('tokens_gerados', 0)} tokens, "
                        f"resto {other:.0f} s) · \"{text[:160]}{'…' if len(text) > 160 else ''}\""))
    used = [t["ferramenta"] for t in answer.get("ferramentas", []) if t.get("ok")]
    checks.append(Check("IA consultou dados reais (ferramentas)", bool(used),
                        ", ".join(used) if used else "respondeu sem consultar nenhuma ferramenta"))

    # Consultar não basta: a resposta precisa USAR o resultado (aconteceu de responder "não sei" com os dados em mãos).
    names = [item["server"]["name"] for item in http.request("GET", "/api/v1/servers")["servers"]]
    if names:
        missing = [n for n in names if n.lower() not in text.lower()]
        # "Não sabe. Caddy: offline..." também é falha: o modelo repetiu a regra em vez de usar os dados.
        denies = text.lower().lstrip(" .,:-").startswith(("não sei", "não sabe", "nao sei", "nao sabe"))
        detail = (f"não cita: {', '.join(missing)}" if missing else
                  "começa dizendo que não sabe, embora tenha os dados" if denies else "cita " + ", ".join(names))
        checks.append(Check("Resposta usa os dados (cita os servidores)", not missing and not denies, detail))

    try:
        loaded = OllamaClient(ai.ollama_url, timeout=15).loaded()
        size = next((m.get("size") for m in loaded if m.get("name") == ai.model or m.get("model") == ai.model), None)
        detail = f"{size / 1024**3:.1f} GB enquanto carregado (liberado após {ai.keep_alive_minutes} min sem uso)" if size else "modelo não aparece como carregado"
    except OllamaError as exc:
        detail = f"não foi possível consultar o Ollama: {exc}"
    checks.append(Check("Memória do modelo (informativo)", True, detail))
    return checks
