# sentinel.modules.security

**Objetivo:** garantir que nenhuma ação ultrapasse o que o usuário autorizou
(PRD 11) e vigiar onde invasores costumam se instalar.

| Arquivo | Responsabilidade |
|---|---|
| `operations.py` | Catálogo fechado de operações: nível de risco, impacto, riscos, alvo e impressão digital |
| `actions.py` | `ActionService`: pedido → aprovação → revalidação → execução única → registro |
| `module.py` | Propostas de recuperação, expiração de pedidos, vigia da inicialização automática |
| `oslayer/autostart.py` | Coleta (registro, Winlogon, IFEO, pastas Inicializar, tarefas, serviços) e avaliação de suspeita |

## Quem aprova

| Quem pede | Aprovação | Exemplo |
|---|---|---|
| Usuário (dashboard/CLI, com confirmação) | o próprio pedido | botão "Reiniciar" |
| Política autorizada pelo usuário | `politica-autorizada` | reinício automático ligado no cadastro |
| Sentinel e a IA (`ia:assistente`) | **pendente até o usuário decidir** | servidor caiu sem política → "Reiniciar X?" |
| Qualquer um, operação nível 3 | pendente + digitar o nome do alvo | (nenhuma operação nível 3 ainda) |

## Garantias (PRD 23.3)

| Cenário | Comportamento |
|---|---|
| Operação fora do catálogo | recusada ("operação não permitida") |
| Aprovação expirada (padrão 30 min) | marcada `expired`; nada executa |
| Alvo alterado após o pedido | impressão digital diferente → pedido `cancelled`; nada executa |
| Aprovação usada duas vezes | `UPDATE` condicional atômico: só a primeira vale |
| Pedido duplicado do Sentinel | reaproveita o pedido aberto |
| Servidor volta sozinho / cadastro excluído | pedido aberto é cancelado |
| Auditoria | toda etapa (pedido, aprovação, rejeição, expiração, execução) em `audit_logs`, somente inserção |

Estados da ação: `pending → approved → executing → completed | failed`, ou
`rejected`, `expired`, `cancelled`.

## Inicialização automática

Varredura a cada 10 min (configurável) e sob demanda. A primeira cria a linha de
base e já aponta itens suspeitos; depois, itens novos ou alterados geram alerta
(**crítico** se suspeitos, **atenção** caso contrário) e removidos, informativo.
Se uma fonte falhar, nada é dado como removido.

Suspeito quando: Shell do Winlogon ≠ `explorer.exe`; Userinit alterado; Debugger
em IFEO; AppInit_DLLs; AutoRun do cmd; script de logon do usuário; interpretador
(cmd, PowerShell, wscript, mshta…) executando de pasta do usuário; nome de
componente do sistema com arquivo em AppData/Temp/Users\Public.

**API:** `/api/v1/actions` (+ `/catalog`, `/{id}`), `/api/v1/approvals` (+ `/{id}/approve|reject`),
`/api/v1/audit`, `/api/v1/security/autostart` (+ `/scan`).
**Configuração:** seção `security`.
**Testes:** `test_security.py`, `test_servers_e2e.py` (fluxo queda → aprovação → reinício).
**Limitações:** sem operações nível 3 ainda; tarefas/serviços que a conta limitada não
enxerga ficam de fora; não substitui um antivírus (PRD 1.4).
