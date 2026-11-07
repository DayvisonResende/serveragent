"""Teste de viabilidade da IA: notas das ferramentas e limpeza do raciocínio, com um Ollama falso."""

from sentinel.agent import ai_benchmark as b
from sentinel.modules.ai.ollama import ChatResult, OllamaClient, OllamaError


def result(content="", calls=None):
    return ChatResult(content, calls or [], "", 1.0, 0.5, 10, 0.1, 50, 5.0)


def test_grading():
    server, process, disk, chat = b.CASES
    assert b._grade(server, result(calls=[{"name": "get_server_status", "arguments": {"server_name": "Moss Blade"}}]))[0]
    assert not b._grade(server, result(calls=[{"name": "get_system_status", "arguments": {}}]))[0]
    assert b._grade(process, result(calls=[{"name": "get_process_list", "arguments": '{"sort_by": "cpu"}'}]))[0]
    assert not b._grade(process, result(calls=[{"name": "get_process_list", "arguments": {"sort_by": "memory"}}]))[0]
    assert not b._grade(disk, result("Você tem 23 GB livres."))[0]  # inventou sem consultar: erro
    assert b._grade(chat, result("Olá! Posso monitorar seus servidores."))[0]
    assert not b._grade(chat, result(calls=[{"name": "get_system_status", "arguments": {}}]))[0]


def test_strip_thinking_variants():
    assert b._strip_thinking("<think>pensando</think>Resposta") == "Resposta"
    assert b._strip_thinking("rascunho</think>\nResposta final") == "Resposta final"
    assert b._strip_thinking("Sem raciocínio") == "Sem raciocínio"


class FakeOllama(OllamaClient):
    def __init__(self, refuse_think=False):
        super().__init__()
        self.refuse_think = refuse_think
        self.calls = []

    def has_model(self, name):
        return True

    def models(self):
        return [{"name": "fake:1b", "size": 10**9}]

    def loaded(self):
        return [{"name": "fake:1b", "size": 1_200_000_000}]

    def unload(self, name):
        pass

    def chat(self, model, messages, tools=None, options=None, keep_alive="5m", think=None):
        self.calls.append(think)
        if think is not None and self.refuse_think:
            raise OllamaError('"fake" does not support thinking')
        question = messages[-1]["content"]
        if tools and "MossBlade" in question:
            return result(calls=[{"name": "get_server_status", "arguments": {"server_name": "MossBlade"}}])
        if tools and "CPU agora" in question:
            return result(calls=[{"name": "get_process_list", "arguments": {"sort_by": "cpu"}}])
        if tools and "espaço livre" in question:
            return result(calls=[{"name": "get_disk_usage", "arguments": {}}])
        return result("<think>x</think>Você tem 23,1 GB livres no C:.")


def test_run_with_fake_ollama_and_think_fallback():
    client = FakeOllama(refuse_think=True)
    lines = []
    reports = b.run(client, pull=False, models=[("LFM3 falso", "hf.co/x/LFM3-fake")], log=lines.append)
    r = reports[0]
    assert r.available and r.tool_score == 4 and r.output_tps == 10.0
    assert r.answer_sample == "Você tem 23,1 GB livres no C:."
    assert any("raciocínio" in n for n in r.notes)
    summary = "\n".join(b.summarize(reports))
    assert "Recomendação: LFM3 falso" in summary


def test_cache_probe_detects_identical_only_reuse():
    """Simula um modelo híbrido: só texto idêntico ao anterior é reaproveitado."""
    from sentinel.agent import ai_cache_probe
    from sentinel.modules.ai.ollama import ChatResult, OllamaClient

    class Hybrid(OllamaClient):
        last = None

        def chat(self, model, messages, tools=None, options=None, keep_alive="5m", think=None):
            key = (str(messages), bool(tools))
            tokens = 1 if key == self.last else (880 if tools else 300)
            self.last = key
            return ChatResult("", [], "", 1.0, 0.0, tokens, tokens / 44, 1, 0.1)

    lines = []
    rows = ai_cache_probe.probe(Hybrid(), "lfm3", "5m", lines.append)
    assert rows["identica"]["lidos"] == 1 and rows["prefixo"]["lidos"] == 880
    verdict = ai_cache_probe.conclude(rows)
    assert "só reaproveita texto IDÊNTICO" in verdict[1] and "66%" in verdict[0]
