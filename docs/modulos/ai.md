# sentinel.modules.ai

**Objetivo:** responder perguntas sobre o computador e os servidores em português,
usando uma IA que roda na própria máquina (Ollama), sempre com base nos dados reais
do Sentinel (PRD 9). A IA não executa nada.

| Arquivo | Responsabilidade |
|---|---|
| `ollama.py` | Cliente HTTP mínimo do Ollama (`/api/chat`, `/api/tags`, `/api/ps`, `/api/pull`), sem dependências |
| `model_profile.py` | Parâmetros recomendados por família de modelo, raciocínio ligado/desligado, limpeza de `<think>` |
| `tools.py` | `ToolBox`: as 8 ferramentas, validação de argumentos, marcação de dados não confiáveis |
| `assistant.py` | `Assistant`: laço pergunta → ferramentas → resposta; histórico em `chat_history` |
| `module.py` | `AIModule`: verifica o Ollama a cada 60 s, publica `ai.availability` quando muda |

## Ferramentas

| Ferramenta | O que devolve |
|---|---|
| `get_system_status` | CPU, memória, discos, rede, alertas ativos |
| `get_processes` | os processos que mais usam CPU ou memória (nomes marcados como não confiáveis) |
| `get_servers` | servidores cadastrados e estados |
| `get_server_details` | estado, verificações e incidentes de um servidor |
| `get_server_logs` | últimas linhas do log (não confiáveis) |
| `get_recent_events` | eventos recentes |
| `get_performance_history` | média e pico de CPU e memória num período |
| `request_server_action` | **cria um pedido pendente** em Aprovações; nunca executa |

Nome de ferramenta desconhecido ou argumento inválido volta ao modelo como
`{"erro": ...}`; nada é executado.

## Limites (settings.yaml, seção `ai`)

| Chave | Padrão | Por quê |
|---|---|---|
| `model` | `hf.co/LiquidAI/LFM3-1.7B-GGUF:Q4_K_M` | medido em 12 tokens/s e 1,1 GB no i3-4150T (D17) |
| `history_messages` | 6 | cada token lido custa tempo de CPU |
| `max_tool_rounds` | 3 | depois disso, uma rodada final sem ferramentas força a resposta |
| `keep_alive_minutes` | 5 | o Ollama libera a RAM do modelo após esse tempo sem uso |
| `timeout_seconds` | 180 | por chamada ao modelo |
| `ollama_url` | `http://127.0.0.1:11434` | só endereços locais são aceitos |

## API

| Rota | Uso |
|---|---|
| `GET /api/v1/ai/status[?refresh=true]` | disponível?, mensagem, modelo, ocupado, preparando |
| `POST /api/v1/ai/warmup` | carrega o modelo e lê as instruções (chamado ao abrir a página; D19) |
| `POST /api/v1/chat` `{message, conversation_id?}` | 200 resposta · 429 outra pergunta em andamento · 503 IA indisponível |
| `GET /api/v1/chat/history?conversation_id=` | mensagens da conversa (com ferramentas usadas e tempo) |

## Verificação

`verificar.bat`, etapa 9 (`sentinel selfcheck --ai`): Ollama e modelo presentes,
o aquecimento, uma pergunta real ("quantos servidores…") pelo mesmo caminho do dashboard,
confirmação de que a IA consultou uma ferramenta e a memória ocupada pelo modelo.
