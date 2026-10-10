# 14. Relatórios e indicadores

## 14.1 Princípios

- **Sem SLA, sem metas:** os indicadores mostram como está o trabalho da equipe, não se um prazo foi cumprido ([10.9](10-chamados.md#109-prazos-sem-sla)).
- **Tempo corrido:** sem calendário de expediente, os tempos são medidos em horas corridas.
- **Mediana em vez de média** nos tempos: um chamado esquecido por um mês não distorce o resultado. A média aparece como informação secundária.
- **Mesma visibilidade dos chamados:** todo relatório aplica o filtro de visibilidade ([8.4](08-organizacao-e-permissoes.md#84-regras-de-visibilidade-de-chamados)). Ninguém vê números de chamados que não poderia abrir.
- **Calculado na hora:** com até 50 usuários, as consultas rodam direto no PostgreSQL, sem tabelas de resumo nem rotinas noturnas.

## 14.2 Filtros comuns

Período (padrão: últimos 30 dias) · Grupo · Responsável · Setor atendido · Categoria · Tipo · Prioridade

## 14.3 Indicadores

| Indicador | Definição | Fonte |
|-----------|-----------|-------|
| **Registrados** | Chamados criados no período | `tickets.created_at` |
| **Concluídos** | Chamados que chegaram a um status `closed` no período | `tickets.closed_at` |
| **Cancelados** | Chamados que chegaram a um status `canceled` no período | `ticket_events` |
| **Em aberto (backlog)** | Chamados não finais no fim do período, por status | `ticket_statuses.kind` |
| **Idade do backlog** | Chamados em aberto por faixa: até 1 dia, 1 a 3 dias, 3 a 7 dias, mais de 7 dias | `created_at` |
| **Tempo na fila** | Do registro até alguém assumir (só os que nasceram sem responsável) | `first_assigned_at − created_at` |
| **Tempo até a conclusão** | Do registro até o status `closed`. Mostrado **bruto** e **líquido** (descontando o tempo em "Aguardando") | `closed_at`, `ticket_events` |
| **Taxa de reabertura** | % dos concluídos com pelo menos uma reabertura | `reopened_count` |
| **Transferências por chamado** | Média de mudanças de grupo | `ticket_events` (`ticket.transferred`) |
| **Demanda por setor** | Chamados registrados e horas medianas por setor atendido | `department_id` |
| **Principais categorias** | As 10 categorias com mais chamados registrados no período | `category_id` |
| **Registrados × concluídos por semana** | Gráfico de linhas: mostra se a fila está crescendo | `created_at`, `closed_at` |

O cálculo do tempo líquido usa os eventos `ticket.status_changed` para somar os intervalos em status `waiting`. A consulta fica isolada em uma *view* SQL comum (`ticket_metrics`), testada com casos de reabertura e de várias idas e voltas para "Aguardando".

## 14.4 Painéis por perfil

| Painel | Quem vê | Conteúdo |
|--------|---------|----------|
| **Meu painel** | Cada membro | Meus chamados em aberto por status · com novidades · concluídos por mim na semana · minha mediana de tempo até a conclusão |
| **Painel do grupo** | Supervisor do grupo (`report.view_team`) | Backlog por status e por idade · registrados × concluídos por semana · chamados por responsável · tempos (mediana) · principais categorias · demanda por setor · taxa de reabertura |
| **Visão geral** | Admin, auditor (`report.view_all`) | Os indicadores do painel do grupo para todos os grupos, lado a lado · usuários ativos no período |

## 14.5 Relatórios em lista (exportáveis em CSV)

| Relatório | Colunas principais |
|-----------|--------------------|
| **Chamados** | Número, título, tipo, categoria, status, prioridade, grupo, responsável, registrado por, setor atendido, pessoa atendida, registrado em, assumido em, concluído em, tempos, reaberturas |
| **Transferências** | Número, de qual grupo, para qual grupo, motivo, quem, quando |

A exportação respeita os mesmos filtros e a visibilidade, e fica registrada na auditoria (`ticket.export`).

## 14.6 Fases

| Fase | Entrega |
|------|---------|
| 1 | Lista de chamados com filtros (já serve de relatório básico) |
| 2 (Sprint 8) | Painéis desta página, view `ticket_metrics`, exportação CSV |
| Futuro | Painel de IA ([6](06-integracao-ia.md#métricas-de-qualidade)) |

A biblioteca de gráficos será escolhida na Sprint 8 (ex.: ECharts ou Chart.js), priorizando acessibilidade e modo escuro, com as cores de [Identidade visual](17-identidade-visual.md).
