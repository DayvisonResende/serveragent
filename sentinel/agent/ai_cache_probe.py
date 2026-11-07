"""Diagnóstico: o Ollama reaproveita a leitura das instruções entre perguntas?

No verificar.bat, cada rodada do chat leu ~880 tokens, sinal de que as
instruções + ferramentas eram relidas toda vez. Hipótese: o LFM3 é um modelo
híbrido (convoluções com estado sequencial); nesse tipo de modelo o Ollama só
reaproveita a leitura anterior quando o novo texto CONTINUA exatamente o
anterior, e não quando diverge no meio (pergunta diferente após as mesmas
instruções).

Mede, com o mesmo início de conversa do assistente:
  1. primeira leitura (modelo já carregado)
  2. o mesmo texto de novo             → reaproveitamento de texto idêntico
  3. mesmas instruções, outra pergunta → reaproveitamento de prefixo
  4. mesmas instruções, sem ferramentas → isola o peso das ferramentas
"""

from __future__ import annotations

from typing import Callable

from sentinel.modules.ai.assistant import SYSTEM_PROMPT
from sentinel.modules.ai.model_profile import options_for, think_flag
from sentinel.modules.ai.ollama import OllamaClient
from sentinel.modules.ai.tools import ToolBox

Q1 = "Como está o computador agora?"
Q2 = "Algum servidor está com problema?"


def probe(client: OllamaClient, model: str, keep_alive: str, log: Callable[[str], None]) -> dict[str, dict[str, float]]:
    tools = ToolBox(None, None, None, None, lambda: []).definitions()  # type: ignore[arg-type]
    options = options_for(model, {"num_predict": 1})
    think = think_flag(model)

    def call(label: str, question: str, with_tools: bool = True) -> dict[str, float]:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question}]
        r = client.chat(model, messages, tools if with_tools else None, options, keep_alive, think)
        row = {"lidos": r.prompt_tokens, "leitura_s": r.prompt_seconds, "total_s": r.total_seconds, "carga_s": r.load_seconds}
        log(f"  {label:<44} {r.prompt_tokens:>5} tokens lidos em {r.prompt_seconds:5.1f} s"
            f"  (total {r.total_seconds:5.1f} s, carga {r.load_seconds:4.1f} s)")
        return row

    log("Carregando o modelo (a primeira chamada não conta)...")
    call("0. aquecimento", "oi")
    log("")
    rows = {
        "primeira": call("1. instruções + pergunta A", Q1),
        "identica": call("2. exatamente o mesmo texto de novo", Q1),
        "prefixo": call("3. mesmas instruções, pergunta B", Q2),
        "sem_ferramentas": call("4. instruções sem ferramentas, pergunta A", Q1, with_tools=False),
    }
    return rows


def conclude(rows: dict[str, dict[str, float]]) -> list[str]:
    first = rows["primeira"]["lidos"] or 1
    same = rows["identica"]["lidos"] / first
    prefix = rows["prefixo"]["lidos"] / first
    tools_share = 1 - rows["sem_ferramentas"]["lidos"] / first
    speed = first / rows["primeira"]["leitura_s"] if rows["primeira"]["leitura_s"] else 0
    out = [f"Velocidade de leitura: {speed:.0f} tokens/s · as ferramentas são {tools_share:.0%} do texto lido."]
    if same < 0.2 and prefix < 0.5:
        out.append("RESULTADO: o Ollama reaproveita o início da conversa. A lentidão não vem da releitura.")
    elif same < 0.2:
        out.append("RESULTADO: o Ollama só reaproveita texto IDÊNTICO; com outra pergunta, relê tudo "
                   "(limitação de modelos híbridos como o LFM3). Aquecer não ajuda; o que ajuda é ler menos texto.")
    else:
        out.append("RESULTADO: o Ollama não reaproveita nada entre chamadas (nem texto idêntico). "
                   "Pode ser configuração do Ollama (ex.: OLLAMA_NUM_PARALLEL) ou da versão.")
    return out
