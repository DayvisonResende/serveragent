# sentinel.modules.notifications

**Objetivo:** avisar fora do dashboard quando algo importante acontecer (PRD 18).
Canal atual: **Telegram**. Desligado até o usuário configurar em *Configurações*.

| Arquivo | Responsabilidade |
|---|---|
| `channels.py` | API do Telegram (getMe, getUpdates, sendMessage), validação do token, erros sem o token |
| `manager.py` | Filtro de eventos, deduplicação, limite por minuto, fila, tentativas, mensagem |
| `oslayer/secrets.py` | Token cifrado com DPAPI no Windows |
| `api/routes/settings.py` | Configuração pelo dashboard (o token só entra, nunca sai) |

## O que é enviado

- Eventos a partir da severidade escolhida (padrão: **Atenção**).
- Sempre: reinícios automáticos (`server.auto_restart`) e encerramento inesperado do Sentinel.
- Recuperações (`server.recovered`), se "avisar quando voltar" estiver marcado.

Mensagem em texto puro (nada é interpretado pelo Telegram):

```
🔴 Crítico · DESKTOP-DPPNGVR
Servidor 'MossBlade Server' offline
nenhum processo do servidor encontrado
05/11 21:44
```

## Proteções

| Risco | Como |
|---|---|
| Enxurrada | máx. 20 mensagens/min; a mesma notícia em 2 min é suprimida e contada |
| Travar o agente | fila de 200 itens e envio numa tarefa própria; fila cheia descarta e conta |
| Falha de rede | 3 novas tentativas (2 s, 5 s, 10 s) |
| Vazamento do token | cifrado em repouso (DPAPI); nunca devolvido pela API; mensagens de erro e logs sem a URL |
| Dados para fora | só título, descrição do alerta e nome do computador — nunca senhas ou conteúdo de logs |

**Limitações:** sem proteção do token fora do Windows (desenvolvimento); DPAPI não
protege contra programa malicioso rodando na mesma conta; notificações do Windows e
e-mail ainda não existem.
**Testes:** `tests/unit/test_notifications.py`, `tests/integration/test_settings_api.py`.
