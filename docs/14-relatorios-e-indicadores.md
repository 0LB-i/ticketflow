# 14. Relatórios e indicadores

## 14.1 Princípios

- **Sem SLA, sem metas:** os indicadores mostram como está o trabalho da equipe, não se um prazo foi cumprido ([10.9](10-chamados.md#109-prazos-sem-sla)).
- **Tempo corrido:** os tempos de chamado são medidos em horas corridas. O expediente cadastrado (§14.7) serve só para as horas extras, não para prazos.
- **Mediana em vez de média** nos tempos: um chamado esquecido por um mês não distorce o resultado. A média aparece como informação secundária.
- **Mesma visibilidade dos chamados:** todo relatório aplica o filtro de visibilidade ([8.4](08-organizacao-e-permissoes.md#84-regras-de-visibilidade-de-chamados)). Ninguém vê números de chamados que não poderia abrir.
- **Calculado na hora:** com até 50 usuários, as consultas rodam direto no PostgreSQL, sem tabelas de resumo nem rotinas noturnas.

## 14.2 Filtros comuns

Período (padrão: últimos 30 dias) · Grupo · Responsável · Categoria · Tipo

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
| **Principais categorias** | As 10 categorias com mais chamados registrados no período | `category_id` |
| **Registrados × concluídos por semana** | Gráfico de linhas: mostra se a fila está crescendo | `created_at`, `closed_at` |

O cálculo do tempo líquido usa os eventos `ticket.status_changed` para somar os intervalos em status `waiting`. A consulta fica isolada em uma *view* SQL comum (`ticket_metrics`), testada com casos de reabertura e de várias idas e voltas para "Aguardando".

## 14.4 Painéis por perfil

| Painel | Quem vê | Conteúdo |
|--------|---------|----------|
| **Meu painel** | Cada membro | Meus chamados em aberto por status · com novidades · concluídos por mim na semana · minha mediana de tempo até a conclusão |
| **Painel do grupo** | Supervisor do grupo (`report.view_team`) | Backlog por status e por idade · registrados × concluídos por semana · chamados por responsável · tempos (mediana) · principais categorias · taxa de reabertura |
| **Visão geral** | Admin, auditor (`report.view_all`) | Os indicadores do painel do grupo para todos os grupos, lado a lado · usuários ativos no período |

## 14.5 Relatórios em lista (exportáveis em CSV)

| Relatório | Colunas principais |
|-----------|--------------------|
| **Chamados** | Número, título, tipo, categoria, status, grupo, responsável, registrado por, pessoa atendida, registrado em, assumido em, concluído em, tempos, reaberturas |
| **Transferências** | Número, de qual grupo, para qual grupo, motivo, quem, quando |

A exportação respeita os mesmos filtros e a visibilidade, e fica registrada na auditoria (`ticket.export`).

## 14.6 Fases

| Fase | Entrega |
|------|---------|
| 1 | Lista de chamados com filtros (já serve de relatório básico) |
| 2026-10-15 | Relatórios de horas, clientes e horas extras, com PDF (§14.7) |
| 2 (Sprint 8) | Painéis desta página, view `ticket_metrics`, exportação CSV |
| 2026-10-24 (Sprint 8) | Relatórios personalizados: modelos salvos, construtor guiado, filtros avançados, CSV e relatório para o cliente (§14.8) |
| Futuro | Painel de IA ([6](06-integracao-ia.md#métricas-de-qualidade)) · envio agendado de relatórios por e-mail (§14.8.7) |

Os gráficos da §14.7 são componentes próprios (barras e colunas de uma série, com os tokens de cor do tema, sem biblioteca). A §14.8 acrescenta linha e colunas empilhadas no mesmo estilo. Uma biblioteca (ex.: ECharts ou Chart.js) só entra se forem pedidos gráficos com interação que eles não cobrem (ex.: zoom).

## 14.7 Relatórios de horas (pedido do usuário, 2026-10-15)

Tela `/relatorios` no menu lateral (não é a tela inicial). Decisões do usuário: painéis prontos com filtros (sem montador de gráficos; revista em 2026-10-24, §14.8), hora extra = tempo **fora do expediente**, cada um vê o seu e o supervisor vê o grupo, PDF gerado na hora pelo botão.

| Item | Definição |
|------|-----------|
| **Filtros** | Período (um dos últimos 12 meses ou duas datas, até 366 dias) · grupo · pessoa · cliente. O PDF usa os mesmos filtros |
| **Horas** | Soma de `time_spent_minutes` das tarefas não removidas com `done_at` no período |
| **Tarefas** | Quantidade de tarefas no período (com ou sem tempo) |
| **Chamados registrados / concluídos** | `created_at` / `closed_at` no período (concluído = status de `kind` `closed` hoje). Com o filtro de pessoa, os chamados em que ela é responsável |
| **Por pessoa** | Horas, horas extras, tarefas e chamados concluídos (cada responsável, principal ou não, conta o chamado) |
| **Por cliente** | Horas, registrados e concluídos; "Sem cliente" agrupa os chamados sem cliente |
| **Por dia** | Horas e horas extras de cada dia (por semana quando o período passa de dois meses) |
| **Hora extra** | A tarefa vai de `done_at − tempo` até `done_at` (`done_at` é quando ela terminou); conta o que cai fora do expediente, em dias que não são de trabalho ou em feriados, no horário da máquina (servidor) |
| **Expediente** | Em Configurações: dias da semana, início e fim (uma faixa por dia) e feriados. Padrão: segunda a sexta, 08:00–18:00 |

**Quem vê o quê:** admin e auditor (`report.view_all`), tudo; quem supervisiona um grupo (`report.view_team`), as tarefas e os chamados dos grupos supervisionados e o próprio trabalho, e pode filtrar pelos membros desses grupos; os demais, só as próprias tarefas e os chamados em que são responsáveis. Sempre em cima do filtro de visibilidade dos chamados. Pedir grupo ou pessoa fora disso responde 403.

**PDF:** A4, no idioma da interface: totais, por pessoa, por cliente e a lista das tarefas fora do expediente. Cada download vai para a auditoria (`report.exported`, com o período e os filtros).

## 14.8 Relatórios personalizados (pedido do usuário, 2026-10-24)

Evolução da §14.7: modelos de relatório salvos, construtor guiado de gráficos, filtros avançados e exportação CSV. Decisões do usuário:

- **Construtor guiado:** a pessoa escolhe em listas fechadas o que agrupar, o que medir e como mostrar, sem SQL nem fórmulas. Substitui o "sem montador de gráficos" da §14.7.
- **Modelos pessoais:** cada pessoa vê e edita só os seus, sem compartilhamento.
- **Uso interno e para o cliente:** o mesmo construtor serve aos dois (§14.8.5).
- **Envio agendado por e-mail:** fica para depois.

### 14.8.1 Modelo de relatório

O modelo guarda a **configuração**, nunca os números. Ao abrir, tudo é calculado de novo com a permissão de quem está vendo ("Quem vê o quê", §14.7).

| Parte | Conteúdo |
|-------|----------|
| **Nome** | Livre |
| **Período** | Relativo (mês atual, mês anterior, últimos 7, 30 ou 90 dias, trimestre atual, trimestre anterior, ano até hoje) ou duas datas fixas. Até 366 dias, como hoje |
| **Filtros** | §14.8.2 |
| **Blocos** | Lista ordenada de cartões, gráficos e tabelas (§14.8.3) |
| **Público** | Interno ou cliente (§14.8.5) |

- **Período relativo:** é o que torna um modelo salvo útil. "Horas por cliente, mês anterior" serve todo mês.
- **Modelos prontos:** Produtividade, Clientes e Horas extras (os painéis da §14.7) e, quando existirem, os painéis da §14.4. Não podem ser apagados, mas dá para duplicar e ajustar.
- **Modelo inicial:** cada pessoa escolhe qual modelo abre ao entrar em Relatórios.
- **Versão da configuração:** a configuração guarda o número da versão do formato. Assim o formato pode mudar sem quebrar os modelos salvos.
- **Na tela (fase 2):** os modelos prontos e os da pessoa são as abas de Relatórios. **Salvar como modelo** cria um modelo com os blocos da aba aberta e o período e os filtros da tela; **Editar modelo** muda o nome, o formato das horas, o modelo inicial e os blocos. O período e os filtros se ajustam na própria tela: num modelo da pessoa, mexer neles mostra **Salvar filtros**.
- **Apagar:** é de verdade (nada aponta para um modelo), com confirmação. Até 50 modelos por pessoa, com nomes que não se repetem.

### 14.8.2 Filtros

| Filtro | Valores |
|--------|---------|
| **Grupo, pessoa, cliente** | Vários de cada; "Sem cliente" é uma das opções |
| **Status** | Vários (o status atual do chamado) |
| **Categoria, tipo** | Vários de cada; entram quando a tela de chamado deixar escolhê-los (hoje não deixa, e todo chamado é "incidente" sem categoria) |
| **Situação do chamado** | Aberto, concluído, cancelado (fase 3, com as medidas de chamados) |
| **Papel da pessoa** | Quem fez a tarefa ou quem é responsável pelo chamado. Por enquanto fixo: nas medidas de tarefas, quem fez; nas de chamados, cada responsável |
| **Só hora extra** | Na fase 2, uma opção do bloco "lista de tarefas" (os outros blocos já têm a medida "horas extras") |
| **Comparar** | Com o período anterior de mesmo tamanho: os cartões mostram a variação (ex.: "+12% vs. mês anterior") |

- **Limite de permissão:** grupo e pessoa continuam limitados ao que a pessoa pode ver (403 fora disso).
- **Filtro que deixou de valer:** se um modelo salvo traz um grupo ou uma pessoa que saiu do alcance de quem o abre (ex.: deixou de ser supervisor), a tela avisa qual filtro não vale mais e não mostra só um erro.

### 14.8.3 Construtor guiado

Cada bloco combina **agrupar por × medida × visual**. A medida define de onde vêm os dados: das tarefas (como na §14.7) ou dos chamados (os indicadores da §14.3).

| Escolha | Opções |
|---------|--------|
| **Agrupar por** | Pessoa, cliente, grupo, status, dia, semana (de segunda a domingo), mês (ou nada, num cartão). Categoria e tipo, quando a tela de chamado os usar (§14.8.2) |
| **Medidas de tarefas** | Horas, horas extras, tarefas |
| **Medidas de chamados** | Registrados e concluídos (fase 2, como na §14.7); cancelados, em aberto, mediana até a conclusão (bruta e líquida), tempo na fila, % de reabertura (fase 3) |
| **Visual** | Cartões (KPI), barras (agrupam por cadastro), colunas, linha (agrupa por período), tabela (várias medidas, uma por coluna, com o total), lista de tarefas. Colunas empilhadas (ex.: horas no expediente + extras) ficam para a fase 3 |
| **Ajustes** | Título do bloco (vazio: um automático, como "Horas por pessoa") · só os N maiores, com o resto em "Outros" · ordem (maior, menor, nome) · horas em `hh:mm` ou em decimal (`7,5 h`), para o modelo todo. As barras já mostram o valor na ponta; as colunas e a linha, na dica |

- **Pessoa e chamado:** agrupado por pessoa, um chamado conta para cada responsável (como os concluídos da §14.7), mas o total da tabela e o cartão contam o chamado uma vez.
- **Períodos vazios:** agrupado por dia, semana ou mês, todos os períodos aparecem, mesmo sem nada. Um gráfico por dia de um período de mais de dois meses agrupa por semana (a tabela e o CSV continuam por dia).

- **Sem linha de meta:** a §14.1 não tem metas.
- **Tempos pela mediana:** a média aparece só como informação secundária (§14.1).
- **Detalhar ao clicar:** clicar numa barra ou numa linha da tabela aplica aquele valor como filtro. Clicar num número de chamados abre a lista de chamados com os mesmos filtros.
- **Catálogo fechado:** as medidas e os agrupamentos são uma lista fixa no código, e cada item tem a sua consulta. Nada do que a pessoa escolhe vira SQL.

### 14.8.4 Exportação CSV

- **Dois tipos:** o CSV de um bloco (a tabela agrupada, como na tela, com o total no fim; ou a lista de tarefas inteira) e o dos dados brutos (a lista de tarefas ou de chamados, com as colunas da §14.5 mais as horas). Todo bloco tem o seu botão de download; na lista de tarefas, a tela mostra as 200 primeiras e o CSV traz todas.
- **Formato:** UTF-8 com BOM, para abrir certo no Excel. Os separadores seguem o idioma: em português, `;` e vírgula decimal. As horas saem em minutos e em horas decimais, para somar na planilha.
- **Injeção de fórmula:** uma célula que começa com `=`, `+`, `-`, `@`, tabulação ou retorno de carro ganha um apóstrofo na frente. Títulos e nomes são texto livre.
- **Visibilidade e auditoria:** valem a mesma visibilidade e o mesmo escopo da tela, e cada download vai para a auditoria (`report.exported`, com o formato).

### 14.8.5 Relatório para o cliente

O modelo de público "cliente" é feito para enviar ao cliente, em PDF.

- **Um cliente:** o filtro precisa ter exatamente um cliente.
- **Cabeçalho:** o logotipo da instalação (Configurações), o nome do cliente e o período.
- **Conteúdo:** totais (horas, chamados registrados e concluídos) e a lista dos chamados do período, com número, título, registrado em, concluído em, status e horas.
- **Quem atendeu:** opcional no modelo, desligado por padrão.
- **Fica de fora:** o texto das tarefas (do chamado aparece só o título, porque as tarefas podem ter anotações internas), o valor por hora, as horas extras, os grupos e qualquer outra informação de organização interna.

### 14.8.6 PDF do modelo

O PDF segue o modelo: título, filtros usados e os blocos na ordem. Os gráficos são desenhados no próprio ReportLab, em vetor. Os modelos prontos da §14.7 continuam com o PDF de hoje.

### 14.8.7 Fases

| Fase | Entrega | Tarefa |
|------|---------|--------|
| 1 | CSV das telas atuais (cada tabela e as tarefas brutas), períodos relativos, grupo, pessoa, cliente (com "Sem cliente") e status com vários valores. Sem tabela nova | F2-S8-04 |
| 2 | Construtor guiado com as medidas de tarefas e os registrados e concluídos, modelos pessoais (tabela `report_models`), modelos prontos, modelo inicial, CSV de cada bloco | F2-S8-05 |
| 3 | Medidas de chamados (§14.3, view `ticket_metrics`), comparação com o período anterior, detalhar ao clicar | F2-S8-06 |
| 4 | PDF do modelo com gráficos e relatório para o cliente | F2-S8-07 |
| Depois | Envio agendado por e-mail, usando o worker e o outbox ([ARCHITECTURE 3.12](../ARCHITECTURE.md)) | — |
