# sentinel.api e dashboard/

**Objetivo:** expor o estado do agente ao dashboard (PRD 14 e 15) sem abrir
brechas, mesmo sendo uma API apenas local.

## Rotas (v1)

| Rota | Sessão | Descrição |
|---|:-:|---|
| `GET /health` | não | `{"status":"ok"}` — sem nenhum dado |
| `GET /login?code=…` | não | troca o código de uso único por um cookie de sessão |
| `GET /api/v1/auth/session` | sim | confirma a sessão |
| `POST /api/v1/auth/logout` | sim | encerra a sessão |
| `GET /api/v1/system/status` | sim | agente, módulos, máquina, amostra atual, discos, temperatura, alertas, IA |
| `GET /api/v1/system/metrics?range=15m\|1h\|6h\|24h\|7d\|30d` | sim | série + resumo (média e pico); até 1 h vem da memória, acima do banco |
| `GET /api/v1/system/processes?sort=cpu\|memory\|name\|runtime&limit=` | sim | lista de processos |
| `GET /api/v1/system/network` | sim | interfaces e taxas |
| `GET /api/v1/system/disks` | sim | partições e tendência de crescimento (7 dias) |
| `GET /api/v1/events?limit=` | sim | eventos recentes |
| `WS /api/v1/ws` | sim | `hello`, `metrics` (a cada 5 s), `event` |

## Segurança

| Ameaça | Defesa |
|---|---|
| Acesso pela rede | Escuta apenas em loopback; outro host é rejeitado na configuração |
| Outro programa ocupando a porta | `SO_EXCLUSIVEADDRUSE` no Windows; porta ocupada → módulo `api` falha, monitor segue |
| DNS rebinding (site malicioso apontando para 127.0.0.1) | `Host` precisa ser 127.0.0.1/localhost/[::1] na porta configurada |
| CSRF / WebSocket entre sites | Cookie `SameSite=Strict` + `Origin` validada em POST/PUT/DELETE e WebSocket |
| Roubo do cookie por script | `HttpOnly`; CSP sem scripts inline; todo dado inserido via `textContent` |
| Senha fraca / força bruta | Não há senha: código aleatório de 256 bits, uso único, válido 2 min, só gerável por quem acessa a pasta do Sentinel; 20 falhas/min → 429 |
| Tokens no banco | Somente SHA-256 de códigos e sessões |
| Clickjacking | `X-Frame-Options: DENY`, `frame-ancestors 'none'` |

Acesso remoto (celular) exigirá senha, HTTPS e rede privada (PRD 17.3) — fase futura.

## Execução embutida

O uvicorn roda no loop do agente (decisão D1). A captura de sinais do uvicorn é
desativada e o socket é aberto pelo Sentinel, para que uma porta ocupada não
derrube o agente (o uvicorn chamaria `sys.exit`).

## Dashboard

HTML/CSS/JS estáticos, sem bibliotecas externas e sem internet. Tema escuro,
responsivo. Páginas: Visão geral, Sistema, Processos, Histórico. Gráficos em SVG:
um eixo por gráfico, legenda, rótulo no fim da linha, linha-guia com tooltip,
tabela de dados e lacunas onde não houve medição. Paleta validada para
daltonismo e contraste sobre o fundo escuro.

**Testes:** `tests/integration/test_api.py`, `test_agent_phase2.py`; `python -m sentinel selfcheck` no agente real.
**Limitações:** sem tema claro; páginas de Servidores, Aprovações, IA e Aprendizado chegam nas fases correspondentes.
