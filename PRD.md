# PRD — SENTINEL
## Agente inteligente de administração, monitoramento e manutenção de servidores Windows

**Versão:** 1.0  
**Status:** Especificação inicial  
**Plataforma principal:** Windows  
**Tipo de aplicação:** Agente local + API + Dashboard Web + Inteligência Artificial  
**Nome do projeto:** Sentinel  
**Objetivo principal:** Administrar, monitorar, proteger, otimizar e aprender sobre o funcionamento do computador e dos servidores hospedados nele.

---

# 1. VISÃO GERAL DO PRODUTO

## 1.1. O que é o Sentinel?

O Sentinel é um agente inteligente executado em segundo plano no Windows, desenvolvido para funcionar como um administrador pessoal do computador e dos servidores hospedados nele.

Seu trabalho é acompanhar continuamente o estado da máquina, identificar problemas, analisar comportamentos, administrar serviços, auxiliar na manutenção e aprender com o funcionamento do ambiente.

O sistema deverá possuir uma interface web acessível pelo navegador, contendo um painel de monitoramento e um chat com inteligência artificial.

O Sentinel deverá conseguir:

- Monitorar o computador em tempo real.
- Acompanhar consumo de CPU, memória RAM, armazenamento e rede.
- Monitorar processos e serviços do Windows.
- Administrar servidores registrados.
- Identificar falhas e comportamentos anormais.
- Analisar arquivos temporários e consumo de armazenamento.
- Recomendar melhorias de desempenho.
- Solicitar autorização antes de executar operações críticas.
- Executar tarefas previamente autorizadas.
- Aprender com instruções do usuário.
- Aprender observando o funcionamento do computador.
- Registrar experiências e resultados de ações.
- Desenvolver procedimentos reutilizáveis.
- Conversar com o usuário por meio de uma IA local.
- Manter histórico das atividades realizadas.

O Sentinel não deverá ser apenas um chatbot que executa comandos. Ele deverá ser um sistema modular de administração, observação, análise, memória e execução controlada.

## 1.2. Filosofia do projeto

O projeto deverá seguir cinco princípios fundamentais:

1. **Autonomia com limites:** o agente pode observar, analisar e recomendar sozinho, mas não pode assumir permissões administrativas por conta própria.
2. **Baixo consumo:** o Sentinel não pode competir significativamente com os servidores hospedados na máquina.
3. **Independência:** os servidores monitorados devem continuar funcionando mesmo se o Sentinel parar.
4. **Rastreabilidade:** todas as ações precisam possuir histórico e justificativa.
5. **Aprendizado progressivo:** o agente deve melhorar sua compreensão do ambiente com o passar do tempo, sem transformar observações em permissões automáticas.

## 1.3. Objetivos

### Objetivos principais

- Criar um administrador local inteligente.
- Centralizar o gerenciamento de serviços e servidores.
- Reduzir a necessidade de administração manual do Windows.
- Antecipar problemas de desempenho.
- Identificar falhas antes que provoquem interrupções maiores.
- Automatizar tarefas repetitivas e seguras.
- Permitir interação em linguagem natural.
- Construir uma memória operacional do computador.

### Objetivos secundários

- Gerar relatórios de utilização.
- Identificar tendências de consumo.
- Detectar processos incomuns.
- Acompanhar disponibilidade dos servidores.
- Recomendar ajustes de configuração.
- Aprender procedimentos aprovados pelo usuário.
- Permitir acesso remoto seguro ao painel.

## 1.4. O que o Sentinel não deverá ser

O Sentinel não deverá:

- Ser um antivírus completo.
- Ser um substituto do Windows Defender.
- Executar comandos arbitrários sugeridos pela IA.
- Excluir arquivos automaticamente sem regras autorizadas.
- Instalar programas sem autorização.
- Alterar firewall ou configurações críticas silenciosamente.
- Reiniciar o computador por decisão própria.
- Interferir nos processos dos servidores para tentar melhorar o desempenho sem autorização.
- Coletar documentos pessoais sem necessidade e autorização.
- Depender da disponibilidade da IA para continuar monitorando.
- Encerrar servidores quando o próprio Sentinel apresentar falhas.

---

# 2. AMBIENTE DE EXECUÇÃO

## 2.1. Hardware de referência

O primeiro ambiente de desenvolvimento e execução será um computador da família Dell OptiPlex 3020.

Configuração de referência informada:

- Memória RAM: 10 GB.
- Armazenamento: SSD.
- Processador: modelo ainda não confirmado.
- Sistema operacional: Windows.
- Conexão de internet: aproximadamente 300 Mbps contratados.
- Upload real: ainda não medido.

A arquitetura deverá ser capaz de funcionar em hardware modesto.

Não se deve assumir que o computador possui recursos suficientes para executar simultaneamente modelos grandes de IA e servidores de jogos.

## 2.2. Prioridade de recursos

A prioridade de utilização da máquina será:

1. Servidores e aplicações hospedadas.
2. Sistema operacional e serviços essenciais.
3. Sentinel.
4. Inteligência artificial e tarefas pesadas do Sentinel.

O Sentinel deverá reduzir suas atividades quando detectar carga elevada nos servidores.

## 2.3. Estratégia de execução

O Sentinel deverá ser dividido em processos independentes:

**Processo A — Core Agent**

Responsável pelo monitoramento básico, agendamento, coleta de métricas e gerenciamento dos módulos.

Deverá permanecer ativo continuamente.

**Processo B — API**

Responsável por comunicação entre o agente e o dashboard.

Poderá permanecer ativo em segundo plano, com baixo consumo.

**Processo C — AI Engine**

Responsável pela integração com Ollama e modelos locais.

Deverá ser carregado somente quando necessário.

**Processo D — Background Workers**

Responsáveis por tarefas como análise de armazenamento, identificação de padrões e geração de relatórios.

Deverão ser executados de acordo com a programação e a disponibilidade de recursos.

**Processo E — Dashboard**

Interface web acessada pelo navegador. Não deverá ser necessário manter uma janela do navegador aberta para que o monitoramento funcione.

## 2.4. Independência dos processos

O Sentinel deverá ser independente dos servidores monitorados.

Se o Sentinel for encerrado:

- Os servidores continuam funcionando.
- O Windows continua funcionando normalmente.
- Nenhum processo monitorado deverá ser encerrado automaticamente.
- O monitoramento será retomado quando o agente iniciar novamente.

---

# 3. ARQUITETURA TECNOLÓGICA

## 3.1. Tecnologias principais

| Camada | Tecnologia |
|---|---|
| Linguagem principal | Python |
| API | FastAPI |
| Comunicação em tempo real | WebSocket |
| Dashboard | HTML, CSS e JavaScript |
| Banco de dados | SQLite |
| Monitoramento | psutil |
| Integração Windows | WMI e APIs nativas |
| Observação de arquivos | watchdog |
| IA local | Ollama |
| Modelo inicial | Liquid AI LFM3-1.7B, sujeito a validação |
| Agendamento | APScheduler ou scheduler próprio |
| Testes | pytest |
| Empacotamento | PyInstaller ou instalação Python controlada |
| Inicialização | Windows Task Scheduler inicialmente |

As tecnologias poderão ser substituídas quando houver justificativa técnica, desde que os contratos entre módulos sejam preservados.

## 3.2. Arquitetura em camadas

O projeto deverá possuir as seguintes camadas:

### Camada 1 — Interface

Responsável por apresentar informações e receber instruções.

Componentes:

- Dashboard.
- Chat.
- Monitoramento.
- Gerenciamento de servidores.
- Gerenciamento de arquivos.
- Central de notificações.
- Histórico.
- Aprovações.
- Configurações.

### Camada 2 — API

Responsável pela comunicação entre interface e agente.

Funções:

- Receber solicitações.
- Validar dados.
- Verificar permissões.
- Consultar módulos.
- Encaminhar solicitações.
- Retornar resultados.
- Transmitir eventos ao dashboard.

### Camada 3 — Core Agent

Responsável por coordenar todo o sistema.

Funções:

- Inicializar módulos.
- Controlar agendamentos.
- Administrar configurações.
- Controlar ciclos de monitoramento.
- Coordenar tarefas.
- Identificar falhas internas.
- Gerenciar o estado do Sentinel.

### Camada 4 — Módulos funcionais

Cada módulo deverá possuir responsabilidade independente.

Módulos:

1. Monitor.
2. Cleaner.
3. Server Manager.
4. Process Manager.
5. AI Engine.
6. Autonomous Learning.
7. Security.
8. Automation.
9. Notification.
10. Diagnostic.
11. Resource Manager.
12. Backup and Recovery.

### Camada 5 — Persistência

Responsável por armazenar:

- Métricas.
- Eventos.
- Processos observados.
- Servidores cadastrados.
- Histórico de ações.
- Aprovações.
- Conversas.
- Memórias.
- Padrões identificados.
- Experiências.
- Procedimentos aprendidos.
- Configurações.

### Camada 6 — Sistema operacional

Responsável pela interação controlada com:

- Processos Windows.
- Serviços Windows.
- Sistema de arquivos.
- Rede.
- Armazenamento.
- Logs.
- Agendador de tarefas.
- Recursos do computador.

---

# 4. ESTRUTURA DE PASTAS

A estrutura inicial recomendada:

```text
sentinel/
│
├── agent/
│   ├── main.py
│   ├── bootstrap.py
│   ├── config.py
│   ├── lifecycle.py
│   ├── scheduler.py
│   └── health.py
│
├── core/
│   ├── event_bus.py
│   ├── module_registry.py
│   ├── task_manager.py
│   ├── resource_manager.py
│   ├── state_manager.py
│   └── exceptions.py
│
├── modules/
│   │
│   ├── monitor/
│   │   ├── cpu.py
│   │   ├── memory.py
│   │   ├── disk.py
│   │   ├── network.py
│   │   ├── temperature.py
│   │   ├── processes.py
│   │   └── collector.py
│   │
│   ├── cleaner/
│   │   ├── analyzer.py
│   │   ├── temporary_files.py
│   │   ├── duplicates.py
│   │   ├── large_files.py
│   │   ├── quarantine.py
│   │   └── cleanup.py
│   │
│   ├── servers/
│   │   ├── registry.py
│   │   ├── health.py
│   │   ├── manager.py
│   │   ├── logs.py
│   │   ├── restart.py
│   │   └── configuration.py
│   │
│   ├── processes/
│   │   ├── inspector.py
│   │   ├── analyzer.py
│   │   └── rules.py
│   │
│   ├── ai/
│   │   ├── ollama.py
│   │   ├── model_manager.py
│   │   ├── assistant.py
│   │   ├── prompt_builder.py
│   │   ├── tools.py
│   │   └── context.py
│   │
│   ├── learning/
│   │   ├── observer.py
│   │   ├── pattern_detector.py
│   │   ├── anomaly_detector.py
│   │   ├── memory_engine.py
│   │   ├── experience_engine.py
│   │   ├── skill_manager.py
│   │   └── evaluator.py
│   │
│   ├── security/
│   │   ├── permissions.py
│   │   ├── approvals.py
│   │   ├── executor.py
│   │   ├── policies.py
│   │   └── audit.py
│   │
│   ├── automation/
│   │   ├── rules.py
│   │   ├── workflows.py
│   │   └── execution.py
│   │
│   ├── notifications/
│   │   ├── manager.py
│   │   └── channels.py
│   │
│   ├── diagnostics/
│   │   ├── analyzer.py
│   │   ├── incidents.py
│   │   └── reports.py
│   │
│   └── backup/
│       ├── database_backup.py
│       └── recovery.py
│
├── api/
│   ├── app.py
│   ├── dependencies.py
│   ├── middleware.py
│   ├── websocket.py
│   └── routes/
│       ├── system.py
│       ├── storage.py
│       ├── processes.py
│       ├── servers.py
│       ├── actions.py
│       ├── approvals.py
│       ├── chat.py
│       ├── learning.py
│       ├── events.py
│       └── settings.py
│
├── dashboard/
│   ├── index.html
│   ├── pages/
│   ├── components/
│   ├── css/
│   ├── js/
│   └── assets/
│
├── database/
│   ├── database.py
│   ├── models.py
│   ├── migrations/
│   └── repositories/
│
├── config/
│   ├── settings.yaml
│   ├── policies.yaml
│   └── servers.yaml
│
├── data/
│   ├── sentinel.db
│   ├── backups/
│   └── quarantine/
│
├── logs/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── security/
│   └── performance/
│
├── scripts/
│   ├── install.ps1
│   ├── uninstall.ps1
│   ├── start.ps1
│   └── diagnostics.ps1
│
├── requirements.txt
├── README.md
└── .env.example
```

A estrutura poderá evoluir. A IA responsável pela construção deverá evitar criar arquivos vazios ou módulos sem responsabilidade definida.

---

# 5. MÓDULO DE MONITORAMENTO DO SISTEMA

## 5.1. Objetivo

Observar continuamente o estado do computador e disponibilizar informações atualizadas ao dashboard, ao sistema de aprendizado e à IA.

O monitoramento básico não poderá depender da IA.

## 5.2. Monitoramento de CPU

Coletar:

- Porcentagem total de utilização.
- Utilização por núcleo, quando disponível.
- Quantidade de núcleos.
- Frequência atual.
- Frequência máxima informada.
- Histórico de utilização.
- Processos com maior consumo.
- Picos de utilização.

Apresentação:

- Gráfico temporal.
- Valor atual.
- Média do período.
- Maior pico.
- Lista dos processos responsáveis.

## 5.3. Monitoramento de memória

Coletar:

- RAM total.
- RAM disponível.
- RAM utilizada.
- Porcentagem de utilização.
- Memória comprometida, quando disponível.
- Memória utilizada pelos processos.
- Paginação e swap, quando aplicável.

O sistema deverá identificar quando o computador estiver próximo de esgotar a memória.

## 5.4. Monitoramento de armazenamento

Coletar:

- Capacidade total.
- Espaço utilizado.
- Espaço livre.
- Porcentagem ocupada.
- Partições.
- Sistemas de arquivos.
- Tendência de crescimento do armazenamento.

Deverá apresentar alertas configuráveis quando o espaço livre estiver abaixo de limites definidos.

## 5.5. Monitoramento de rede

Coletar:

- Upload.
- Download.
- Taxa atual de transferência.
- Bytes enviados.
- Bytes recebidos.
- Interfaces de rede.
- Endereços locais.
- Conexões relevantes, quando disponíveis.
- Erros e desconexões.

Não deverá realizar inspeção de conteúdo privado do tráfego.

## 5.6. Temperatura

Tentar obter informações de sensores disponíveis.

Caso o hardware ou driver não disponibilize esses dados, apresentar:

"Sensor de temperatura indisponível."

Nunca inventar valores ou estimar temperaturas como se fossem medições reais.

## 5.7. Monitoramento de processos

Coletar:

- PID.
- Nome.
- Caminho executável, quando permitido.
- CPU.
- Memória.
- Horário de início.
- Estado.
- Usuário proprietário, quando disponível.

Permitir ordenar processos por:

- Maior uso de CPU.
- Maior uso de memória.
- Tempo de execução.
- Nome.

O módulo deverá ser somente de observação na primeira versão.

## 5.8. Frequência de coleta

Valores iniciais sugeridos:

| Indicador | Intervalo |
|---|---:|
| CPU | 5 segundos |
| RAM | 5 segundos |
| Disco | 30 segundos |
| Rede | 5 segundos |
| Processos principais | 15 segundos |
| Temperatura | 30 segundos |
| Uptime | 60 segundos |

Os intervalos deverão ser configuráveis.

O sistema deverá reduzir a frequência de coleta quando houver carga elevada na máquina.

---

# 6. MÓDULO DE GERENCIAMENTO DE SERVIDORES

## 6.1. Objetivo

Permitir que o Sentinel administre servidores e aplicações hospedadas no computador.

O sistema deverá suportar diferentes tecnologias, não apenas Node.js.

Exemplos:

- Servidor de jogos.
- Servidor Node.js.
- Servidor Python.
- Banco de dados.
- Cloudflare Tunnel.
- Aplicações web.
- Serviços Windows.
- Outros processos cadastrados.

## 6.2. Cadastro de servidores

O usuário deverá conseguir cadastrar um servidor manualmente.

Campos:

- Nome.
- Descrição.
- Categoria.
- Caminho do projeto.
- Executável.
- Argumentos permitidos.
- Diretório de trabalho.
- Porta.
- Protocolo.
- Tipo de gerenciamento.
- PID, quando conhecido.
- Estratégia de inicialização.
- Estratégia de verificação.
- Política de reinicialização.
- Criticidade.
- Ativo ou inativo.

Exemplo:

```json
{
  "name": "Servidor de Jogo",
  "type": "node",
  "working_directory": "D:/Servers/Game",
  "executable": "node.exe",
  "arguments": ["server.js"],
  "port": 3000,
  "protocol": "http",
  "health_check": {
    "type": "http",
    "path": "/health"
  },
  "criticality": "high"
}
```

Os caminhos e comandos do cadastro devem ser tratados como dados de configuração não confiáveis até serem validados e aprovados.

## 6.3. Estados do servidor

Cada servidor deverá possuir um estado:

- Online.
- Offline.
- Inicializando.
- Reiniciando.
- Com problemas.
- Sem resposta.
- Desconhecido.
- Desativado.

Não considerar um servidor saudável apenas porque seu processo está ativo.

## 6.4. Verificação de saúde

O Sentinel deverá oferecer diferentes estratégias:

### Verificação por processo

Confirma se o processo está ativo.

### Verificação por porta

Confirma se a porta está escutando.

### Verificação HTTP

Realiza uma requisição a um endpoint de saúde.

### Verificação TCP

Testa se uma conexão TCP pode ser estabelecida.

### Verificação personalizada

Permite criar verificações controladas e limitadas.

## 6.5. Gerenciamento

Funcionalidades:

- Iniciar servidor.
- Parar servidor.
- Reiniciar servidor.
- Consultar estado.
- Consultar logs.
- Consultar consumo de recursos.
- Consultar disponibilidade.
- Consultar histórico de incidentes.

Operações de inicialização, parada e reinicialização deverão exigir aprovação, salvo se existir uma política específica e limitada autorizada pelo usuário.

## 6.6. Reinicialização segura

Fluxo:

1. Detectar indisponibilidade.
2. Registrar incidente.
3. Verificar se o processo ainda está ativo.
4. Realizar verificações adicionais.
5. Consultar política de recuperação.
6. Solicitar aprovação, quando necessária.
7. Executar a operação permitida.
8. Aguardar inicialização.
9. Verificar novamente a saúde.
10. Registrar resultado.

Evitar ciclos infinitos de reinicialização.

Deverá existir limite de tentativas e período de espera progressivo.

---

# 7. MÓDULO DE PROCESSOS

## 7.1. Objetivo

Oferecer uma visão organizada dos processos em execução e permitir diagnósticos controlados.

## 7.2. Funcionalidades

- Listar processos.
- Identificar processos com alto consumo.
- Identificar processos que consomem memória continuamente.
- Comparar consumo ao longo do tempo.
- Associar processos aos servidores cadastrados.
- Detectar processos que desapareceram.
- Detectar processos inesperados em diretórios monitorados.
- Mostrar histórico de utilização.

## 7.3. Proteções

Na primeira versão, o Sentinel não deverá finalizar processos arbitrários.

A finalização de um processo deverá ser limitada a processos registrados e a operações aprovadas.

Processos essenciais do Windows deverão possuir proteção especial.

---

# 8. MÓDULO DE LIMPEZA E ARMAZENAMENTO

## 8.1. Objetivo

Analisar o armazenamento, identificar desperdícios e propor ações para liberar espaço.

## 8.2. Categorias de análise

- Arquivos temporários.
- Logs antigos.
- Arquivos grandes.
- Arquivos duplicados.
- Pastas com crescimento elevado.
- Arquivos esquecidos em diretórios monitorados.
- Dados temporários de aplicações.

## 8.3. Análise de arquivos

O Sentinel deverá conseguir:

- Identificar tamanho.
- Identificar extensão.
- Registrar data de criação e modificação, quando disponível.
- Identificar diretório.
- Calcular hash para comparação de conteúdo.
- Identificar arquivos duplicados.
- Agrupar arquivos por categoria.

O hash deverá ser calculado apenas quando necessário, pois a leitura de muitos arquivos pode consumir bastante disco e CPU.

## 8.4. Sistema de limpeza

A limpeza deverá possuir quatro etapas:

1. Análise.
2. Recomendação.
3. Aprovação.
4. Execução.

Nunca executar exclusão permanente apenas porque a IA recomendou.

## 8.5. Quarentena

Sempre que possível, arquivos removidos deverão ser transferidos para uma pasta de quarentena.

O sistema deverá registrar:

- Arquivo original.
- Localização original.
- Data.
- Motivo.
- Tamanho.
- Hash.
- Ação executada.
- Possibilidade de restauração.

A quarentena deverá possuir limite de espaço e política de retenção.

## 8.6. Exclusões proibidas por padrão

Não permitir limpeza automática de:

- Arquivos do Windows.
- Pastas de inicialização.
- Arquivos de sistema.
- Bancos de dados ativos.
- Diretórios de servidores cadastrados.
- Arquivos desconhecidos com função crítica.
- Arquivos pessoais fora do escopo autorizado.

## 8.7. Dashboard de armazenamento

Exibir:

- Espaço total.
- Espaço livre.
- Principais diretórios.
- Arquivos grandes.
- Duplicados encontrados.
- Espaço potencialmente recuperável.
- Histórico de crescimento.
- Relatórios de limpeza.

O espaço potencialmente recuperável deverá ser uma estimativa identificada como tal, não uma promessa.

---

# 9. MÓDULO DE INTELIGÊNCIA ARTIFICIAL

## 9.1. Objetivo

Permitir que o usuário converse com o Sentinel e utilize linguagem natural para consultar o computador, compreender problemas e solicitar operações.

## 9.2. Modelo inicial

Integração prevista com Ollama e um modelo local da família Liquid AI, inicialmente considerando LFM3-1.7B.

A compatibilidade real do modelo, formato, quantização, consumo e suporte a chamadas de ferramentas deverão ser validados antes da implementação.

A arquitetura deverá permitir trocar de modelo sem reescrever o sistema.

## 9.3. Funcionamento

O usuário poderá escrever:

- "Como está meu servidor?"
- "Por que minha memória está quase cheia?"
- "Qual processo está consumindo mais CPU?"
- "Quanto espaço posso liberar?"
- "Meu servidor de jogos está funcionando?"
- "O que aconteceu durante a madrugada?"
- "Analise o comportamento do computador nos últimos sete dias."
- "Quais problemas você identificou?"
- "Quais melhorias você recomenda?"

A IA deverá consultar as ferramentas adequadas e responder com base nos dados reais.

## 9.4. Ferramentas disponíveis para a IA

Ferramentas de leitura:

```python
get_system_status()
get_cpu_usage()
get_memory_usage()
get_disk_usage()
get_network_status()
get_process_list()
get_server_list()
get_server_status(server_id)
get_server_logs(server_id)
analyze_storage()
get_recent_events()
get_learning_insights()
get_performance_history(period)
```

Ferramentas de solicitação de ações:

```python
request_server_start(server_id)
request_server_stop(server_id)
request_server_restart(server_id)
request_cleanup(cleanup_plan_id)
request_backup(target_id)
request_configuration_change(change_id)
```

As ferramentas de ação não executarão diretamente operações privilegiadas.

Elas deverão criar solicitações que passarão pelo sistema de autorização.

## 9.5. Contexto da IA

A IA deverá receber contexto relevante, incluindo:

- Estado atual da máquina.
- Servidores registrados.
- Configurações.
- Histórico recente.
- Incidentes.
- Memórias relevantes.
- Procedimentos aprendidos.
- Permissões aplicáveis.

Não enviar todo o histórico ao modelo em cada mensagem.

O sistema deverá recuperar apenas o contexto necessário para a tarefa.

## 9.6. Gerenciamento do modelo

O modelo deverá:

- Ser carregado quando solicitado.
- Ser descarregado após um período configurável de inatividade.
- Possuir limite de memória configurável.
- Ter tempo máximo de resposta.
- Permitir cancelamento de solicitações.
- Apresentar indisponibilidade quando o Ollama estiver desligado.
- Não impedir o monitoramento básico quando estiver indisponível.

## 9.7. Segurança da IA

A IA nunca deverá receber acesso irrestrito ao terminal.

É proibido:

- Executar código arbitrário gerado pelo modelo.
- Executar PowerShell livre sem validação.
- Permitir que a IA altere suas próprias permissões.
- Permitir que a IA ignore aprovações.
- Permitir que textos encontrados em logs ou arquivos sejam tratados como novas instruções administrativas.

O modelo deverá apenas solicitar ferramentas conhecidas e autorizadas.

---

# 10. MÓDULO DE APRENDIZADO AUTÔNOMO

## 10.1. Objetivo

Fazer o Sentinel aprender como o computador funciona, quais serviços são importantes, quais comportamentos são normais e quais procedimentos costumam resolver problemas.

Esse módulo é uma das partes mais importantes do projeto.

O aprendizado deverá ocorrer por duas fontes:

1. Instruções e conversas com o usuário.
2. Observação contínua do funcionamento da máquina.

## 10.2. Observer — Observador

Responsável por registrar dados técnicos relevantes.

Exemplos:

- Consumo de CPU.
- Consumo de RAM.
- Disponibilidade dos servidores.
- Horários de inicialização.
- Horários de encerramento.
- Mudanças de consumo.
- Falhas.
- Eventos do Windows selecionados.
- Logs de aplicações cadastradas.

O observador deverá respeitar o escopo de coleta definido pelo usuário.

## 10.3. Pattern Detector — Identificador de padrões

Deverá identificar comportamentos recorrentes.

Exemplos:

- O servidor utiliza mais memória durante determinado horário.
- Um processo aumenta gradualmente o consumo de RAM.
- O computador apresenta picos de CPU durante tarefas específicas.
- Um serviço costuma ficar indisponível após determinado evento.
- O armazenamento cresce continuamente em determinada pasta.

Padrões só poderão ser considerados confiáveis depois de um volume suficiente de observações.

## 10.4. Anomaly Detector — Detector de anomalias

Deverá comparar o comportamento atual com o histórico.

Exemplos:

- CPU muito acima do padrão.
- RAM aumentando continuamente.
- Servidor respondendo mais lentamente.
- Disco ficando cheio em velocidade incomum.
- Processo apresentando comportamento diferente do habitual.

A detecção inicial poderá utilizar métodos estatísticos simples.

Não é necessário utilizar IA generativa para cada análise.

Métodos possíveis:

- Média móvel.
- Desvio padrão.
- Percentis.
- Comparação com períodos equivalentes.
- Limites configuráveis.
- Detecção de tendências.

## 10.5. Memory Engine — Sistema de memória

O Sentinel deverá manter uma memória operacional.

Tipos de memória:

### Memória de ambiente

Armazena informações sobre o computador.

Exemplo:

"Este computador hospeda um servidor de jogos Node.js na porta 3000."

### Memória de preferência

Armazena instruções do usuário.

Exemplo:

"Não reiniciar o servidor de jogos durante períodos de atividade."

### Memória de padrão

Armazena comportamentos observados.

Exemplo:

"O consumo de memória do servidor aumenta durante períodos de maior atividade."

### Memória de experiência

Armazena problemas encontrados, procedimentos utilizados e resultados.

### Memória de procedimento

Armazena sequências de ações aprovadas e reutilizáveis.

## 10.6. Experience Engine — Sistema de experiências

Cada incidente relevante deverá poder gerar uma experiência.

Exemplo:

```json
{
  "incident": "Servidor indisponível",
  "observation": "Processo Node.js encerrado",
  "action": "Reinicialização aprovada",
  "result": "Servidor voltou a responder",
  "success": true,
  "confidence": 0.85
}
```

O Sentinel deverá conseguir consultar experiências semelhantes em situações futuras.

## 10.7. Skill Manager — Aprendizado de procedimentos

O agente poderá construir procedimentos reutilizáveis a partir de ações aprovadas.

Exemplo:

Procedimento: recuperar servidor Node.js.

Etapas:

1. Consultar estado do servidor.
2. Verificar processo.
3. Consultar logs.
4. Identificar causa provável.
5. Solicitar autorização.
6. Reiniciar o servidor registrado.
7. Confirmar disponibilidade.
8. Registrar resultado.

O procedimento não poderá conter comandos arbitrários ou privilégios ocultos.

## 10.8. Knowledge Evaluator — Avaliador de conhecimento

Cada aprendizado deverá possuir:

- Origem.
- Evidências.
- Quantidade de observações.
- Período analisado.
- Confiança.
- Última ocorrência.
- Possíveis explicações alternativas.
- Estado de validação.

O Sentinel deverá diferenciar:

- Fato observado.
- Hipótese.
- Padrão provável.
- Conclusão confirmada pelo usuário.

Não transformar correlação em causalidade.

## 10.9. Aprendizado não significa autorização

Esta regra é obrigatória.

Se o Sentinel aprender que reiniciar determinado servidor costuma resolver uma falha, isso não significa que poderá reiniciá-lo automaticamente.

O aprendizado melhora a capacidade de diagnóstico e recomendação.

A autorização continuará sendo controlada pelo módulo de segurança.

## 10.10. Aprendizado sem IA constante

O aprendizado deverá utilizar Python para:

- Coletar métricas.
- Comparar períodos.
- Identificar tendências.
- Calcular estatísticas.
- Detectar anomalias.
- Registrar experiências.

A IA local será acionada para interpretar, explicar e ajudar a transformar descobertas em procedimentos.

---

# 11. MÓDULO DE SEGURANÇA E PERMISSÕES

## 11.1. Objetivo

Garantir que nenhuma ação do Sentinel ultrapasse os limites definidos pelo usuário.

## 11.2. Níveis de permissão

### Nível 0 — Observação

Permitido automaticamente:

- Consultar CPU.
- Consultar RAM.
- Consultar disco.
- Consultar processos.
- Consultar servidores.
- Ler logs autorizados.
- Registrar métricas.
- Gerar relatórios.

### Nível 1 — Operações leves

Poderão ser autorizadas por políticas específicas:

- Atualizar estatísticas.
- Gerar relatórios.
- Organizar dados internos do Sentinel.
- Rotacionar logs próprios.
- Ajustar frequência de monitoramento dentro de limites.

### Nível 2 — Operações que exigem aprovação

- Reiniciar servidor.
- Parar servidor.
- Iniciar servidor.
- Limpar arquivos.
- Mover arquivos.
- Restaurar arquivos.
- Alterar configurações de aplicações.
- Executar manutenção.

### Nível 3 — Operações críticas

Exigem aprovação explícita e confirmação adicional:

- Alterar firewall.
- Instalar programas.
- Modificar serviços do Windows.
- Alterar permissões.
- Excluir arquivos de forma permanente.
- Alterar configurações de rede.
- Encerrar processos críticos.
- Executar operações administrativas.

O Sentinel não deverá realizar essas operações silenciosamente.

## 11.3. Sistema de aprovação

Cada ação deverá gerar uma solicitação com:

- Identificador.
- Nome da ação.
- Justificativa.
- Alvo.
- Impacto esperado.
- Riscos.
- Recursos afetados.
- Horário.
- Estado.
- Prazo de validade.

Estados:

- Pendente.
- Aprovada.
- Rejeitada.
- Expirada.
- Executando.
- Concluída.
- Falhou.
- Cancelada.

## 11.4. Fluxo de aprovação

1. IA ou módulo solicita uma operação.
2. Security valida a operação.
3. Sentinel cria uma solicitação.
4. Dashboard apresenta os detalhes.
5. Usuário aprova ou rejeita.
6. O sistema revalida o estado do alvo.
7. Executor realiza somente a operação autorizada.
8. Resultado é registrado.
9. Dashboard recebe atualização.

Uma aprovação deverá ser vinculada à ação e ao alvo específicos. Não poderá ser reutilizada para operações diferentes.

## 11.5. Executor restrito

O executor deverá aceitar identificadores de operações previamente cadastradas.

Exemplo:

```python
ALLOWED_OPERATIONS = {
    "server_start",
    "server_stop",
    "server_restart",
    "cleanup_quarantine",
    "create_backup"
}
```

Cada operação deverá possuir validação própria.

Não implementar uma função genérica como:

```python
execute_command(command_from_ai)
```

## 11.6. Auditoria

Registrar:

- Quem solicitou.
- Qual módulo solicitou.
- Qual ação.
- Motivo.
- Aprovação.
- Data.
- Resultado.
- Erros.
- Recursos afetados.

O histórico de auditoria não poderá ser editado pela IA ou pelo dashboard.

---

# 12. MÓDULO DE AUTOMAÇÃO

## 12.1. Objetivo

Permitir que o Sentinel execute rotinas previamente definidas e autorizadas.

## 12.2. Exemplos

- Verificar servidores a cada 15 segundos.
- Analisar armazenamento diariamente.
- Gerar relatório diário.
- Alertar quando o espaço livre estiver baixo.
- Verificar crescimento anormal de memória.
- Fazer backup periódico do banco de dados do Sentinel.

## 12.3. Políticas

Toda automação deverá possuir:

- Nome.
- Descrição.
- Gatilho.
- Condição.
- Ação.
- Permissões necessárias.
- Frequência.
- Limite de tentativas.
- Política de falha.
- Estado ativo ou inativo.

## 12.4. Autonomia configurável

O usuário poderá escolher entre:

1. Observar e aprender, solicitando aprovação para mudanças.
2. Observar, aprender e ajustar parâmetros não críticos automaticamente, dentro de limites.
3. Apenas observar e apresentar descobertas.

A opção padrão recomendada é a primeira.

---

# 13. GERENCIAMENTO DE RECURSOS

## 13.1. Objetivo

Evitar que o Sentinel prejudique o desempenho dos servidores hospedados.

## 13.2. Limites iniciais

Metas de engenharia, não benchmarks garantidos:

| Recurso | Meta inicial |
|---|---|
| RAM do núcleo | 200 MB ou menos, quando viável |
| CPU em repouso | Abaixo de 1–3% em média |
| Coleta básica | Leve e contínua |
| IA | Sob demanda |
| Análise profunda | Programada ou manual |

O consumo real deverá ser medido nos testes.

## 13.3. Modo de baixa prioridade

Quando o computador estiver sob pressão, o Sentinel deverá:

- Reduzir frequência de coleta não essencial.
- Pausar análise de armazenamento.
- Pausar cálculos pesados de aprendizado.
- Evitar scans completos.
- Adiar tarefas não urgentes.
- Não iniciar modelos de IA automaticamente.

## 13.4. Proteção dos servidores

Os processos registrados como servidores prioritários deverão ser tratados como processos protegidos.

O Sentinel não deverá encerrar, suspender ou modificar esses processos para liberar recursos, exceto quando uma política explícita e uma aprovação válida autorizarem uma operação específica.

---

# 14. DASHBOARD WEB

## 14.1. Objetivo

Criar uma interface moderna, organizada e intuitiva para administrar o Sentinel.

A interface deverá funcionar em:

- Computador.
- Tablet.
- Celular.

## 14.2. Identidade visual

Direção visual sugerida:

- Interface tecnológica.
- Aparência profissional.
- Tema escuro como padrão.
- Contraste adequado.
- Gráficos limpos.
- Informações organizadas.
- Alertas visuais claros.
- Responsividade.

Evitar excesso de informações na tela inicial.

## 14.3. Navegação principal

Menu:

1. Visão geral.
2. Sistema.
3. Servidores.
4. Processos.
5. Armazenamento.
6. Inteligência artificial.
7. Aprendizado.
8. Automações.
9. Aprovações.
10. Histórico.
11. Configurações.

## 14.4. Página inicial — Overview

Deverá mostrar:

### Estado do computador

- CPU.
- RAM.
- Disco.
- Rede.
- Uptime.
- Temperatura, quando disponível.

### Estado dos servidores

- Quantidade total.
- Quantidade online.
- Quantidade offline.
- Servidores com problemas.

### Estado do Sentinel

- Agente ativo.
- IA disponível ou indisponível.
- Última coleta.
- Módulos ativos.
- Tarefas em execução.

### Alertas

- Falhas.
- Alto consumo.
- Pouco espaço.
- Servidores indisponíveis.
- Solicitações pendentes.

### Atividade recente

- Ações realizadas.
- Incidentes.
- Descobertas.
- Aprovações.
- Relatórios.

## 14.5. Página de servidores

Cada servidor deverá possuir um cartão contendo:

- Nome.
- Estado.
- Porta.
- PID.
- CPU.
- RAM.
- Tempo ativo.
- Última verificação.
- Histórico recente.

A página de detalhes deverá apresentar:

- Gráficos de consumo.
- Logs.
- Eventos.
- Verificações de saúde.
- Histórico de reinicializações.
- Configurações.
- Botões de operação sujeitos a autorização.

## 14.6. Página de armazenamento

Apresentar:

- Capacidade.
- Espaço livre.
- Diretórios maiores.
- Arquivos grandes.
- Duplicados.
- Possíveis arquivos temporários.
- Relatórios de limpeza.
- Quarentena.

## 14.7. Página de aprendizado

Uma das páginas mais importantes.

Deverá mostrar o que o Sentinel está aprendendo.

Categorias:

- Padrões identificados.
- Anomalias.
- Experiências.
- Memórias.
- Procedimentos aprendidos.
- Descobertas aguardando validação.

Cada descoberta deverá apresentar:

- O que foi observado.
- Quando foi observado.
- Evidências.
- Quantidade de ocorrências.
- Confiança.
- Interpretação.
- Ação recomendada.

O usuário poderá confirmar, corrigir ou descartar uma conclusão.

## 14.8. Página de aprovações

Exibir:

- Solicitações pendentes.
- Risco.
- Justificativa.
- Alvo.
- Operação.
- Consequências.
- Botão aprovar.
- Botão rejeitar.

Operações críticas deverão exigir confirmação adicional.

## 14.9. Chat com IA

O chat deverá permitir:

- Perguntas sobre o computador.
- Consultas aos servidores.
- Análise de incidentes.
- Solicitação de relatórios.
- Recomendações.
- Solicitação de operações.
- Consulta ao aprendizado.

A IA deverá mostrar quando estiver utilizando dados reais, quando estiver apresentando hipóteses e quando não possuir informações suficientes.

---

# 15. API E COMUNICAÇÃO

## 15.1. API REST

Endpoints iniciais:

```text
GET    /api/system/status
GET    /api/system/metrics
GET    /api/system/processes
GET    /api/system/network

GET    /api/storage/analysis
GET    /api/storage/large-files
GET    /api/storage/duplicates
GET    /api/storage/reports

GET    /api/servers
POST   /api/servers
GET    /api/servers/{id}
PUT    /api/servers/{id}
DELETE /api/servers/{id}

GET    /api/servers/{id}/health
GET    /api/servers/{id}/logs

POST   /api/actions
GET    /api/actions
GET    /api/actions/{id}

GET    /api/approvals
POST   /api/approvals/{id}/approve
POST   /api/approvals/{id}/reject

POST   /api/chat
GET    /api/chat/history

GET    /api/learning/insights
GET    /api/learning/memories
GET    /api/learning/experiences
GET    /api/learning/skills

GET    /api/events
GET    /api/settings
PUT    /api/settings
```

Os endpoints de exclusão e alteração deverão possuir verificações de permissão e auditoria.

## 15.2. WebSocket

Utilizado para transmitir:

- Métricas.
- Eventos.
- Alertas.
- Mudanças no estado dos servidores.
- Estado do agente.
- Progresso das tarefas.
- Resultado de ações.

O dashboard deverá reconectar automaticamente caso a conexão seja interrompida.

## 15.3. Versionamento

A API deverá possuir versionamento desde o início, por exemplo:

```text
/api/v1/system/status
```

---

# 16. BANCO DE DADOS

SQLite será utilizado inicialmente.

A camada de acesso ao banco deverá ser isolada para permitir uma migração futura para PostgreSQL, se necessário.

## 16.1. Tabelas principais

### system_metrics

```text
id
timestamp
cpu_percent
ram_used
ram_available
disk_used
disk_free
network_upload
network_download
```

### process_snapshots

```text
id
timestamp
pid
process_name
executable_path
cpu_percent
memory_bytes
status
```

### servers

```text
id
name
description
server_type
working_directory
executable
arguments_json
port
protocol
health_check_json
criticality
enabled
created_at
updated_at
```

### server_checks

```text
id
server_id
timestamp
process_alive
port_available
health_status
response_time
error_message
```

### events

```text
id
event_type
severity
source
title
description
metadata_json
timestamp
```

### actions

```text
id
action_type
target
requested_by
reason
status
approval_id
started_at
completed_at
result_json
error_message
```

### approvals

```text
id
action_id
requested_at
expires_at
approved_at
rejected_at
approved_by
status
```

### cleanup_reports

```text
id
created_at
files_found
bytes_recoverable
files_moved
files_deleted
status
details_json
```

### chat_history

```text
id
conversation_id
role
message
context_json
timestamp
```

### learning_observations

```text
id
observation_type
source
data_json
timestamp
```

### learning_patterns

```text
id
pattern_type
description
evidence_json
observation_count
confidence
first_seen
last_seen
status
```

### learning_memories

```text
id
memory_type
content
source
confidence
created_at
updated_at
expires_at
```

### learning_experiences

```text
id
incident_id
observation
action_taken
outcome
success
evidence_json
created_at
```

### learning_skills

```text
id
name
description
procedure_json
permissions_required
validation_status
created_at
updated_at
```

### policies

```text
id
name
scope
rule_json
enabled
created_at
updated_at
```

### audit_logs

```text
id
actor
operation
target
reason
approval_id
result
timestamp
```

## 16.2. Retenção

O sistema deverá permitir configurar a retenção de dados.

Opções propostas:

- 30 dias.
- 90 dias.
- 1 ano.
- Retenção prolongada com rotação.

A retenção deverá ser configurável por categoria.

Métricas brutas poderão ser agregadas em médias e percentis históricos para reduzir o crescimento do banco.

Logs, auditoria e dados de incidentes deverão possuir políticas próprias.

## 16.3. Integridade

Implementar:

- Índices.
- Migrações.
- Transações.
- Backup.
- Controle de concorrência.
- Rotação de dados.
- Verificação de integridade.

O banco deverá utilizar operações assíncronas ou um padrão de acesso que não bloqueie o monitoramento durante gravações.

---

# 17. SEGURANÇA DO AMBIENTE

## 17.1. Execução do agente

O Sentinel deverá executar inicialmente com uma conta de usuário de privilégios limitados.

Não executar o sistema inteiro como administrador.

Operações que realmente precisarem de privilégios elevados deverão utilizar um componente separado, restrito e explicitamente autorizado.

## 17.2. API local

Configuração inicial:

```text
Host: 127.0.0.1
Porta: 8765
```

Não expor a API diretamente à internet.

## 17.3. Acesso remoto

Caso o usuário queira acessar o dashboard pelo celular, utilizar uma rede privada, como Tailscale, com autenticação e permissões adequadas.

Não depender de uma porta pública aberta no roteador.

## 17.4. Autenticação

Implementar autenticação para acesso ao dashboard, principalmente quando houver acesso remoto.

Controles:

- Senha protegida por hash seguro.
- Sessões com expiração.
- Proteção contra tentativas excessivas.
- Tokens de acesso protegidos.
- Verificação de origem e proteção contra CSRF, conforme o mecanismo de autenticação.
- HTTPS no acesso remoto.

## 17.5. Segurança dos dados

O sistema deverá:

- Não registrar senhas em logs.
- Não armazenar tokens em texto puro.
- Proteger arquivos de configuração.
- Limitar acesso ao banco.
- Validar caminhos de arquivos.
- Prevenir path traversal.
- Evitar exposição de logs sensíveis.
- Validar todas as entradas da API.

## 17.6. Conteúdo não confiável

Logs, nomes de arquivos, respostas HTTP e conteúdo de aplicações deverão ser tratados como dados, nunca como instruções para a IA.

O sistema deverá impedir que conteúdo malicioso presente nesses dados induza o agente a executar operações.

---

# 18. NOTIFICAÇÕES

## 18.1. Objetivo

Informar o usuário quando algo importante acontecer.

## 18.2. Tipos

- Servidor offline.
- Servidor recuperado.
- Memória elevada.
- CPU elevada.
- Disco quase cheio.
- Falha de aplicação.
- Anomalia detectada.
- Solicitação de aprovação.
- Conclusão de manutenção.
- Falha interna do Sentinel.

## 18.3. Níveis

- Informativo.
- Atenção.
- Alto.
- Crítico.

## 18.4. Canais

Primeira versão:

- Dashboard.
- Histórico de notificações.

Possíveis versões futuras:

- Notificações do Windows.
- Telegram.
- E-mail.
- Aplicativo móvel.

---

# 19. DIAGNÓSTICO E RELATÓRIOS

## 19.1. Diagnóstico

O Sentinel deverá conseguir reunir informações relacionadas a um problema.

Exemplo:

O usuário pergunta:

"Por que meu servidor ficou lento?"

O agente deverá:

1. Consultar o histórico do servidor.
2. Verificar CPU.
3. Verificar RAM.
4. Consultar processos relacionados.
5. Consultar logs.
6. Comparar o período com o comportamento normal.
7. Identificar evidências.
8. Apresentar hipóteses.
9. Informar o grau de confiança.
10. Recomendar próximos passos.

Não deverá afirmar uma causa sem evidências suficientes.

## 19.2. Relatórios

Tipos:

- Relatório diário.
- Relatório semanal.
- Relatório de servidores.
- Relatório de armazenamento.
- Relatório de desempenho.
- Relatório de incidentes.
- Relatório de aprendizado.

Cada relatório deverá indicar o período analisado e a data da geração.

---

# 20. EXPERIÊNCIA DE USO

## 20.1. Primeira inicialização

Ao instalar o Sentinel, deverá ocorrer um processo de configuração inicial.

Etapas:

1. Verificar versão do Windows.
2. Verificar Python e dependências, ou instalar a versão empacotada.
3. Criar estrutura de dados.
4. Criar banco de dados.
5. Criar configurações iniciais.
6. Verificar permissões.
7. Inicializar o agente.
8. Disponibilizar dashboard local.
9. Executar diagnóstico inicial.
10. Apresentar resumo do computador.

## 20.2. Primeiro diagnóstico

O Sentinel deverá apresentar:

- Hardware detectado.
- RAM.
- CPU.
- Discos.
- Interfaces de rede.
- Processos principais.
- Serviços identificáveis.
- Estado do Ollama.
- Recursos disponíveis.
- Limitações encontradas.

O usuário poderá cadastrar seus servidores manualmente.

## 20.3. Interação cotidiana

O usuário deverá conseguir abrir o dashboard e entender rapidamente:

- Se o computador está saudável.
- Se os servidores estão online.
- Se existe algum problema.
- O que o Sentinel aprendeu.
- Se existe alguma ação aguardando aprovação.

---

# 21. CONFIGURAÇÕES DO USUÁRIO

Todas as principais configurações deverão ser editáveis no dashboard.

## 21.1. Monitoramento

- Frequência de coleta.
- Indicadores monitorados.
- Limites de alerta.
- Processos protegidos.
- Servidores prioritários.

## 21.2. Aprendizado

- Aprendizado automático ativado.
- Observação contínua.
- Escopo de dados.
- Retenção de histórico.
- Confiança mínima para apresentar descobertas.
- Revisão de memórias.

## 21.3. Autonomia

Opções:

1. Observar e aprender, solicitando aprovação para mudanças.
2. Ajustar automaticamente parâmetros não críticos dentro de limites.
3. Apenas observar e apresentar descobertas.

## 21.4. Inteligência artificial

- Modelo.
- Endereço do Ollama.
- Tempo de inatividade.
- Limite de memória.
- Temperatura e parâmetros do modelo.
- Timeout.
- Ativação automática ou manual.

## 21.5. Recursos

- Limite de CPU.
- Limite de memória.
- Modo econômico.
- Frequência de tarefas pesadas.
- Pausa automática durante alta carga.

---

# 22. REQUISITOS NÃO FUNCIONAIS

## 22.1. Desempenho

O sistema deverá:

- Consumir poucos recursos em repouso.
- Evitar operações bloqueantes.
- Não executar scans completos constantemente.
- Utilizar cache quando apropriado.
- Fazer coleta incremental.
- Agrupar gravações no banco quando seguro.
- Limitar concorrência de tarefas.
- Evitar sobrecarregar o disco.

## 22.2. Confiabilidade

- Reinicialização automática do agente em caso de falha.
- Recuperação do estado após reinicialização do Windows.
- Integridade do banco.
- Tratamento de exceções.
- Timeout para operações.
- Cancelamento de tarefas.
- Registro de erros.

A recuperação do agente não deverá reiniciar os servidores monitorados.

## 22.3. Disponibilidade

O monitoramento básico deverá continuar mesmo se:

- Ollama estiver desligado.
- O modelo de IA estiver indisponível.
- O dashboard estiver fechado.
- A internet cair.
- Uma tarefa de análise falhar.

## 22.4. Manutenibilidade

- Código modular.
- Tipagem quando aplicável.
- Documentação.
- Testes automatizados.
- Logs estruturados.
- Configuração centralizada.
- Interfaces claras entre módulos.

## 22.5. Portabilidade futura

Embora a primeira versão seja para Windows, evitar dependências desnecessárias que impeçam uma futura adaptação para Linux.

As operações específicas do Windows deverão ficar isoladas em uma camada de integração.

---

# 23. TESTES E CRITÉRIOS DE QUALIDADE

## 23.1. Testes unitários

Testar individualmente:

- Coleta de CPU.
- Coleta de RAM.
- Coleta de disco.
- Coleta de rede.
- Identificação de processos.
- Verificação de servidores.
- Cálculo de hashes.
- Análise de padrões.
- Sistema de permissões.
- Sistema de aprovações.
- Registro de auditoria.

## 23.2. Testes de integração

Verificar:

- API comunicando com o Core.
- Dashboard recebendo métricas.
- WebSocket reconectando.
- SQLite persistindo dados.
- Ollama respondendo.
- IA solicitando ferramentas.
- Executor validando permissões.
- Aprovações funcionando.
- Módulos funcionando de forma independente.

## 23.3. Testes de segurança

Simular:

- Solicitação de comando não permitido.
- Aprovação expirada.
- Alteração de alvo após aprovação.
- Caminho de arquivo inválido.
- Tentativa de acessar arquivo fora do escopo.
- Conteúdo malicioso em logs.
- Tentativa de acesso não autenticado.
- Falha do executor.
- Reinicialização não autorizada.

## 23.4. Testes de desempenho

Executar o Sentinel junto com aplicações e servidores simulados.

Medir:

- RAM do agente.
- CPU do agente.
- Operações de disco.
- Frequência de coleta.
- Tempo de resposta da API.
- Crescimento do banco.
- Efeito da IA sobre a máquina.
- Efeito de análises pesadas.

A medição deverá separar o consumo do Sentinel do consumo do modelo de IA.

---

# 24. MVP — VERSÃO 0.1

O MVP deverá entregar uma versão funcional, segura e utilizável.

Não tentar implementar todos os módulos avançados de uma só vez.

## 24.1. Funcionalidades obrigatórias

- Inicialização automática no Windows.
- Core Agent em segundo plano.
- Monitoramento de CPU.
- Monitoramento de RAM.
- Monitoramento de disco.
- Monitoramento de rede.
- Lista de processos.
- Dashboard web.
- Cadastro de servidores.
- Verificação de disponibilidade.
- Registro de eventos.
- Sistema de aprovações.
- Reinicialização controlada de um servidor registrado.
- Histórico de ações.
- Chat básico com Ollama.
- Ferramentas de consulta para IA.

## 24.2. Critérios de conclusão

O MVP será considerado concluído quando:

1. O Sentinel iniciar no Windows.
2. O dashboard mostrar dados reais.
3. O agente continuar funcionando sem o dashboard aberto.
4. Um servidor puder ser cadastrado.
5. O Sentinel identificar quando esse servidor ficar indisponível.
6. O Sentinel registrar o incidente.
7. O usuário receber uma solicitação de aprovação.
8. Uma reinicialização aprovada puder ser executada.
9. O sistema verificar se o servidor voltou a funcionar.
10. A operação ficar registrada no histórico.
11. O Sentinel continuar monitorando quando o Ollama estiver indisponível.
12. Os servidores continuarem funcionando quando o Sentinel for encerrado.

---

# 25. ROADMAP DE DESENVOLVIMENTO

## Fase 1 — Fundação

Objetivo: criar a estrutura do sistema.

Entregas:

- Estrutura de pastas.
- Configurações.
- Core Agent.
- Banco SQLite.
- Sistema de logs.
- Inicialização.
- Gerenciamento de módulos.

## Fase 2 — Monitoramento

Objetivo: observar o computador.

Entregas:

- CPU.
- RAM.
- Disco.
- Rede.
- Processos.
- Histórico.
- API.
- Dashboard inicial.

## Fase 3 — Gerenciamento de servidores

Objetivo: administrar aplicações hospedadas.

Entregas:

- Cadastro.
- Monitoramento.
- Health checks.
- Logs.
- Eventos.
- Reinicialização controlada.

## Fase 4 — Segurança

Objetivo: controlar as operações.

Entregas:

- Permissões.
- Aprovações.
- Executor restrito.
- Auditoria.
- Proteção de operações críticas.

## Fase 5 — Inteligência artificial

Objetivo: permitir interação em linguagem natural.

Entregas:

- Integração Ollama.
- Gerenciamento de modelo.
- Chat.
- Contexto.
- Ferramentas.
- Solicitação de ações.

## Fase 6 — Limpeza e diagnóstico

Objetivo: realizar manutenção assistida.

Entregas:

- Análise de armazenamento.
- Arquivos grandes.
- Duplicados.
- Quarentena.
- Relatórios.
- Diagnóstico.

## Fase 7 — Aprendizado autônomo

Objetivo: construir memória operacional.

Entregas:

- Observer.
- Pattern Detector.
- Anomaly Detector.
- Memory Engine.
- Experience Engine.
- Skill Manager.
- Knowledge Evaluator.

## Fase 8 — Automação inteligente

Objetivo: permitir rotinas controladas.

Entregas:

- Regras.
- Agendamentos.
- Políticas.
- Alertas.
- Recuperação autorizada.
- Ajustes não críticos.

## Fase 9 — Evolução

Objetivo: tornar o Sentinel mais completo.

Possibilidades:

- Acesso remoto seguro.
- Notificações externas.
- PostgreSQL.
- Gerenciamento avançado de serviços.
- Interface móvel.
- Relatórios avançados.
- Diagnóstico preditivo.
- Integração com outros computadores.

---

# 26. REGRAS OBRIGATÓRIAS PARA A IA QUE CONSTRUIRÁ O SENTINEL

Esta seção deverá ser tratada como instrução de implementação.

## 26.1. Construção incremental

Não desenvolver o sistema inteiro em um único arquivo.

Não implementar todos os módulos simultaneamente.

Construir uma fase por vez, mantendo o sistema funcional após cada etapa.

## 26.2. Não simular funcionalidades

É proibido:

- Exibir métricas fictícias como se fossem reais.
- Criar servidores fictícios automaticamente sem identificação.
- Simular resultados de operações.
- Apresentar IA como conectada quando estiver indisponível.
- Mostrar temperatura inexistente.
- Informar que uma ação foi concluída antes da confirmação real.

Quando um recurso não estiver disponível, apresentar seu estado corretamente.

## 26.3. Implementar funcionalidades completas

Uma funcionalidade não estará concluída apenas porque possui uma tela.

Exemplo: o botão de reiniciar servidor deverá possuir:

- Validação.
- Permissão.
- Aprovação.
- Execução.
- Tratamento de erro.
- Verificação do resultado.
- Auditoria.

## 26.4. Não ignorar erros

Toda operação deverá possuir tratamento de exceções.

Falhas deverão ser registradas e apresentadas de maneira compreensível.

Não utilizar blocos de exceção que ocultem erros silenciosamente.

## 26.5. Não permitir acesso irrestrito à IA

O modelo nunca deverá controlar diretamente o sistema operacional.

Toda operação deverá passar por ferramentas e validações explícitas.

## 26.6. Documentar

Cada módulo deverá possuir documentação explicando:

- Objetivo.
- Responsabilidades.
- Entradas.
- Saídas.
- Dependências.
- Permissões.
- Configurações.
- Testes.
- Limitações.

## 26.7. Preservar o funcionamento

Antes de implementar uma nova funcionalidade:

1. Analisar a arquitetura existente.
2. Identificar dependências.
3. Planejar alterações.
4. Preservar contratos de API.
5. Criar ou atualizar testes.
6. Implementar.
7. Testar.
8. Documentar.

Não reescrever módulos funcionais sem necessidade.

## 26.8. Não aumentar privilégios automaticamente

A IA construtora não deverá implementar mecanismos para que o Sentinel obtenha privilégios administrativos por conta própria.

## 26.9. Configurações devem ser externas

Evitar valores importantes fixos no código.

Utilizar arquivos de configuração e banco de dados.

## 26.10. Entrega de cada fase

Ao terminar uma fase, apresentar:

- O que foi desenvolvido.
- Arquivos criados.
- Arquivos alterados.
- Funcionalidades concluídas.
- Testes executados.
- Resultados.
- Problemas conhecidos.
- Próximas etapas.

Não marcar tarefas como concluídas sem implementação e teste.

---

# 27. DEFINIÇÃO DE PRONTO

Uma funcionalidade será considerada pronta quando:

- Estiver implementada.
- Estiver integrada à arquitetura.
- Possuir validação de entrada.
- Possuir tratamento de erros.
- Respeitar permissões.
- Possuir testes adequados.
- Possuir documentação.
- Não apresentar dados fictícios.
- Não comprometer a estabilidade do sistema.

Uma fase será considerada pronta quando todos os seus critérios de aceitação forem atendidos.

---

# 28. VISÃO FINAL DO SENTINEL

O Sentinel deverá evoluir de um simples monitor de sistema para um administrador inteligente do ambiente computacional.

Sua evolução deverá seguir este caminho:

**Primeiro:** observar o computador.

**Depois:** compreender os servidores.

**Em seguida:** identificar problemas.

**Então:** explicar o que está acontecendo.

**Depois:** recomendar soluções.

**Em seguida:** executar operações autorizadas.

**Finalmente:** aprender com as experiências e reconhecer padrões cada vez mais complexos.

O resultado esperado é um agente que conhece o ambiente em que trabalha, entende como os serviços se comportam, acompanha sua saúde, aprende com o histórico e ajuda o usuário a administrar tudo de forma centralizada.

A inteligência do Sentinel não deverá estar apenas no modelo de IA. Ela deverá estar distribuída em sua arquitetura, nos dados coletados, na memória operacional, nas regras de segurança, no histórico e nos procedimentos aprendidos.

**Princípio definitivo do projeto:**

O Sentinel pode aprender sozinho, analisar sozinho e recomendar sozinho. Mas só poderá modificar o ambiente dentro dos limites de autonomia explicitamente concedidos pelo usuário.


Diálogos extras:

Sentinel — Seu administrador inteligente de computador e servidores
Imagine ter alguém trabalhando nos bastidores do seu computador 24 horas por dia, observando tudo, entendendo como as coisas funcionam e ajudando a manter seus sistemas funcionando corretamente.

Esse é o Sentinel.

O Sentinel é um agente inteligente de administração e gerenciamento de computadores e servidores. Ele funciona em segundo plano no Windows, acompanha o funcionamento da máquina, monitora os serviços em execução, identifica problemas, aprende com o ambiente e ajuda a executar tarefas de manutenção.

Mas ele não é apenas um monitor de desempenho, nem simplesmente uma inteligência artificial com acesso ao computador. Ele combina monitoramento, automação, memória, aprendizado e execução controlada em um único sistema.
O que o Sentinel pode fazer?









1. Conhecer e monitorar o computador

Acompanha CPU, memória RAM, armazenamento, rede, processos, serviços e outros indicadores. Sabe o que está acontecendo na máquina e mantém um histórico do seu funcionamento.












2. Administrar servidores

Gerencia servidores de jogos, aplicações Node.js, bancos de dados e outros serviços. Verifica se estão funcionando, acompanha seus recursos, consulta logs e pode solicitar reinicializações quando identifica falhas.












3. Cuidar da manutenção

Analisa arquivos temporários, identifica arquivos grandes e duplicados, acompanha o crescimento do armazenamento e recomenda formas de liberar espaço com segurança.












4. Conversar e entender solicitações

Possui um assistente de IA local. Você pode perguntar sobre o computador, pedir diagnósticos, solicitar relatórios e pedir que ele execute operações autorizadas usando linguagem natural.












5. Aprender com o ambiente

Observa o comportamento do computador, identifica padrões, reconhece anomalias e registra experiências. Com o tempo, constrói uma memória operacional sobre os servidores e serviços que administra.












6. Tomar iniciativas com responsabilidade

Pode identificar problemas, investigar causas, recomendar soluções e preparar ações. Operações críticas dependem da autorização do usuário, respeitando regras e permissões.



Um exemplo de como ele funciona na prática
Imagine que você tenha um servidor de jogo rodando no computador.

Durante a madrugada, o servidor começa a consumir cada vez mais memória. O Sentinel percebe que esse comportamento está diferente do habitual.

Ele registra a ocorrência, compara com o histórico, analisa os processos e procura informações nos logs.

Pela manhã, você abre o dashboard e encontra uma mensagem:
Sentinel
Atenção

Descoberta automática · 04:32

Identifiquei um aumento contínuo no consumo de memória do seu servidor de jogos.
- Consumo inicial: 1,2 GB
- Consumo atual: 3,8 GB
- Período observado: 4 horas
- Comportamento: crescimento progressivo
Minha análise

O comportamento pode indicar um vazamento de memória, mas ainda não tenho evidências suficientes para confirmar a causa.

Minha recomendação

Investigar os logs e analisar o comportamento do processo antes de considerar uma reinicialização.

Exemplo ilustrativo de interface e análise.

Você pode conversar com ele, pedir uma investigação mais profunda e decidir o que fazer.

É assim que o Sentinel deve trabalhar: observar, compreender, aprender e ajudar.
Como ele funciona?
O Sentinel possui três características importantes:
- Sempre presente: seu núcleo permanece ativo em segundo plano, mesmo quando o dashboard está fechado.
- Inteligência sob demanda: a IA local é acionada quando necessária, evitando consumir memória continuamente.
- Independente dos servidores: se o Sentinel parar, os servidores continuam funcionando.
Ele não precisa estar pensando o tempo inteiro para estar trabalhando.
O que torna o Sentinel diferente?
Um monitor tradicional mostra números. Um gerenciador tradicional executa comandos. Um chatbot responde perguntas.

O Sentinel pretende reunir essas três capacidades e ir além: construir conhecimento sobre o ambiente que administra.

Ele não deve apenas saber que um servidor está consumindo 90% da memória. Deve conseguir compreender se isso é normal, comparar com o histórico, investigar o motivo provável e ajudar a resolver o problema.

Em essência, o Sentinel é um administrador digital que conhece seu computador, acompanha seus servidores, aprende com o funcionamento do ambiente e trabalha para mantê-lo saudável, estável e organizado.

Seu propósito não é substituir o usuário, mas assumir o trabalho de observação, diagnóstico e manutenção que normalmente exigiria atenção humana constante.

















Ele consegue executar ações sozinhas?













Sim. O Sentinel pode executar ações sozinho, sem precisar que você autorize cada vez, desde que você defina quais ações ele tem permissão para realizar.

Na verdade, essa é uma das características que pode torná-lo muito mais interessante: ele não seria apenas um programa que avisa quando algo está errado, mas um agente capaz de identificar problemas, tomar decisões dentro de limites e agir.
3 níveis de autonomia do Sentinel
1. Autonomia de observação
Baixo risco

Ele monitora o computador, aprende padrões, identifica anomalias e apresenta diagnósticos.

Exemplo: percebe que um servidor está consumindo cada vez mais memória e identifica um possível vazamento.


2. Autonomia operacional
Pode agir sozinho

Ele executa tarefas previamente autorizadas.

Exemplos:
- Limpar arquivos temporários dentro de limites definidos.
- Reiniciar um serviço específico quando ele parar.
- Reiniciar uma aplicação que travou.
- Gerar backups programados.
- Reduzir a frequência de monitoramento quando o servidor estiver sobrecarregado.
- Gerar relatórios e alertas.


3. Autonomia administrativa
Exige autorização

Ele pode investigar e propor mudanças mais profundas, mas precisa da sua aprovação.

Exemplos:
- Alterar configurações do Windows.
- Instalar ou remover programas.
- Alterar regras de firewall.
- Excluir arquivos importantes.
- Modificar configurações dos servidores.


Um exemplo de como ele trabalharia sozinho
Imagine que você está dormindo e o servidor do seu jogo começa a apresentar problemas.
1. 02:00 — Detecção
   
   Sentinel percebe que o servidor do jogo parou de responder.
2. 02:01 — Investigação
   
   Analisa o processo, os registros e o histórico para identificar o problema.
3. 02:02 — Decisão
   
   Identifica que o processo encerrou inesperadamente e que existe uma rotina de recuperação autorizada.
4. 02:03 — Execução
   
   Reinicia o servidor usando o procedimento aprovado.
5. 02:04 — Verificação
   
   Confirma se o servidor voltou a responder.
6. 02:05 — Aprendizado
   
   Registra o incidente, a causa provável, a ação executada e o resultado.
Problema recuperado sem intervenção humana

O que eu faria de diferente no Sentinel
Eu criaria um sistema chamado Autonomia Progressiva.

O Sentinel começaria com permissões limitadas. Conforme acumulasse experiências, demonstrasse que suas ações são confiáveis e você aprovasse seus procedimentos, poderia receber autorização para executar determinadas rotinas automaticamente.

Mas existe uma regra fundamental:

Aprender a fazer alguma coisa não significa ganhar autorização para fazê-la.

Por exemplo, ele pode aprender a reinstalar um serviço, mas isso não significa que possa reinstalá-lo sem sua permissão.

Minha visão é que o Sentinel deve ser capaz de administrar boa parte da rotina do computador e dos servidores sozinho, mas nunca ter liberdade irrestrita para modificar o sistema.

Isso permitiria que ele fosse realmente autônomo sem colocar seu computador ou seus servidores em risco.
