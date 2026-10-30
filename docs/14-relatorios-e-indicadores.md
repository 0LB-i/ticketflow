# 14. Relatórios e indicadores

## 14.1 Princípios

- **Sem SLA, sem metas:** os indicadores mostram como está o trabalho da equipe, não se um prazo foi cumprido ([10.9](10-chamados.md#109-prazos-sem-sla)).
- **Tempo corrido:** os tempos de chamado são medidos em horas corridas. Os expedientes cadastrados (§14.7: da instalação, dos grupos e das pessoas) servem só para as horas extras e as tarefas por dia útil, não para prazos.
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
| **Tempo na fila** | Do registro até alguém assumir (só os que nasceram sem responsável). Fora dos relatórios desde 2026-10-24: todo chamado nasce com responsável (migração 0028), e a medida seria sempre zero | `first_assigned_at − created_at` |
| **Tempo até a conclusão** | Do registro até o status `closed`. Mostrado **bruto** e **líquido** (descontando o tempo em "Aguardando") | `closed_at`, `ticket_events` |
| **Taxa de reabertura** | % dos concluídos com pelo menos uma reabertura | `reopened_count` |
| **Transferências por chamado** | Média de mudanças de grupo | `ticket_events` (`ticket.transferred`) |
| **Principais categorias** | As 10 categorias com mais chamados registrados no período | `category_id` |
| **Registrados × concluídos por semana** | Gráfico de linhas: mostra se a fila está crescendo | `created_at`, `closed_at` |

O cálculo do tempo líquido usa os eventos `ticket.status_changed` para somar os intervalos em status `waiting` e, num chamado reaberto, o tempo em que ele ficou concluído antes da reabertura. Ele é feito em Python (`reports/service.net_minutes`, no lugar da *view* `ticket_metrics` planejada antes), testado com reabertura, várias idas e voltas para "Aguardando" e conclusão com data informada.

**Em aberto no fim do período:** registrados até o fim e não concluídos nem cancelados antes dele (pelas datas de conclusão e de cancelamento, as mesmas das medidas). O status de cada um no fim é o "de" da primeira mudança de status depois dele (sem mudança, o atual); agrupado por status, vale esse status.

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
| 2026-10-28 | Relatórios simplificados: só as abas prontas, sem modelos pessoais nem editor (§14.8) |
| Futuro | Painel de IA ([6](06-integracao-ia.md#métricas-de-qualidade)) · envio agendado de relatórios por e-mail (§14.8.7) |

Os gráficos da §14.7 são componentes próprios (barras e colunas de uma série, com os tokens de cor do tema, sem biblioteca). A §14.8 acrescenta a linha no mesmo estilo. Uma biblioteca (ex.: ECharts ou Chart.js) só entra se forem pedidos gráficos com interação que eles não cobrem (ex.: zoom).

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
| **Hora extra** | A tarefa vai de `done_at − tempo` até `done_at` (`done_at` é quando ela terminou); conta o que cai fora do expediente **de quem a fez**, em dias que não são de trabalho dela ou em feriados, no horário da máquina (servidor). Cada dia que a tarefa atravessa usa o expediente daquele dia (uma tarefa que passa da meia-noite usa o do dia seguinte na parte depois dela). O PDF e o CSV dizem o expediente usado, e a tela não, desde 2026-10-27 ("Expediente usado": o da instalação e, quando houver, os dos grupos e os próprios que valeram no período, só de quem a pessoa vê; no CSV das tarefas, a coluna "Expediente", tarefa por tarefa) |
| **Expediente** | Dias da semana, início e fim (uma faixa por dia). Há o **da instalação** (Configurações, `admin.settings`; padrão segunda a sexta, 08:00–18:00), o **de um grupo** (painel do grupo, `admin.organization`) e o **de uma pessoa** (painel do usuário, `admin.users`), sem permissão nova; toda mudança vai para a auditoria. **Precedência** (2026-10-27): o da pessoa > o do grupo > o da instalação. O do grupo vale para quem está em **um só** grupo ativo com expediente; quem está em dois ou mais precisa de um próprio e, até ter, segue o da instalação (o painel do usuário avisa). Vale a participação **atual** nos grupos: não há histórico de participação, então quem muda de grupo leva o expediente novo também para os dias de antes (as vigências do grupo e da pessoa não mudam). **Vigência:** todo expediente vale a partir de uma data, até a próxima vigência do mesmo dono; mudar grava uma vigência nova (por padrão, a partir de hoje) e não muda a hora extra dos dias de antes. O da instalação de antes desta regra vale desde sempre. Para voltar ao de cima, a pessoa ou o grupo ganha uma vigência "sem expediente próprio" a partir de uma data; uma vigência nova na mesma data substitui a que estava (é assim que se corrige uma futura), e não há exclusão. **Feriados:** só os da instalação (Configurações), para todos |

**Quem vê o quê:** admin e auditor (`report.view_all`), tudo; quem supervisiona um grupo (`report.view_team`), as tarefas e os chamados dos grupos supervisionados e o próprio trabalho, e pode filtrar pelos membros desses grupos; os demais, só as próprias tarefas e os chamados em que são responsáveis. Sempre em cima do filtro de visibilidade dos chamados. Pedir grupo ou pessoa fora disso responde 403.

**PDF:** desde 2026-10-27, o menu Baixar das abas Produtividade, Clientes e Horas extras gera o PDF da aba (§14.8.6), com os blocos de cada uma. A API (`GET /api/v1/reports/pdf`) continua igual por fora (endereço, parâmetros, `locale`, auditoria), porque é contrato para integrações: A4 em pé, no idioma pedido, com o período, os filtros e o expediente no cabeçalho, os totais, por pessoa, por cliente e as tarefas fora do expediente, **as 200 primeiras** (como a tela), com a nota "Mostrando as 200 primeiras de N tarefas. O CSV traz todas." (antes vinha a lista inteira: um mês cheio passava de 140 páginas); em cada página, o "Gerado em…" (sem o nome de quem gerou, desde 2026-10-28) e o número da página. Cada download vai para a auditoria (`report.exported`, com o período e os filtros).

**Aba Clientes** (pedido do usuário, 2026-10-27): abre só com os chamados **concluídos** (os status de situação concluída valem sem filtro na URL, e o link da aba os leva quando a tela não tem status escolhido; tirar a etiqueta mostra todos). O menu Baixar tem dois PDFs: o **simplificado**, o da aba (os blocos), e o **detalhado**, que antes dos blocos traz uma tabela por cliente (pelo nome, "Sem cliente" no fim) com cada tarefa do período, sem o corte das 200: o dia, o chamado (número e título; o texto da tarefa fica de fora, porque pode ter anotação interna) e o tempo, com o total do cliente. Os blocos vêm depois, como o resumo (os cartões com o título "Resumo do período"). A auditoria registra `table=detailed`. **Hora extra** (2026-10-27): um seletor ao lado do Comparar, só nesta aba (`extras=separada` na URL). **Sem separação** (o padrão), todo o tempo é de trabalho normal: os cartões e a tabela mostram só as horas, sem as horas extras, e o PDF não traz a frase do expediente. **Separada**, os cartões e a tabela por cliente mostram as horas, as horas no expediente e as horas extras (as duas somam as horas); o PDF detalhado ganha as colunas "Horas no expediente" e "Horas extras" antes do tempo de cada tarefa e no total de cada cliente, e os PDFs trazem a frase do expediente usado no cabeçalho. A escolha não é filtro: não conta para "sem filtro na URL". **Plano do cliente** (2026-10-28): o contrato do cliente (cadastro, bloco Contrato: mensal ou anual com as horas, ou chamado avulso) separa as horas **no plano** das **excedentes**, sempre, nos cartões e na tabela por cliente (depois das horas no expediente e das extras, quando separadas) e no PDF detalhado (as duas colunas antes do tempo de cada tarefa e no total de cada cliente). O mensal vale por mês do calendário e o anual por ano do calendário; consome o plano **todo o trabalho feito para o cliente** no mês ou no ano, sem o escopo nem os filtros da tela (inclusive as tarefas de antes do período), na ordem em que as tarefas terminaram: a que passa do limite tem excedente só a parte de fora, e as seguintes são inteiras excedentes. A tela mostra o excedente das tarefas que aparecem nela. Avulso, cliente sem contrato e "Sem cliente": todas as horas são excedentes. Vale o contrato de hoje (o cadastro não guarda o histórico). **Horas descontadas** (2026-10-28): com a aba filtrada por **um cliente só**, um campo ao lado da hora extra recebe as horas descontadas, em horas e minutos ("2:30", "2h30", "2h"; `desconto` na URL; o que não se entende fica de fora, com o aviso). Elas abatem as primeiras horas do período, na ordem das tarefas, com ou sem plano, e a tela mostra, depois das horas, as **horas descontadas** e as **horas a cobrar** (horas − descontadas), nos cartões, na tabela e no PDF detalhado (depois do tempo, tarefa a tarefa e no total); os gráficos mostram as horas a cobrar no lugar das horas. Sem desconto, nada disso aparece. O desconto é do período: o comparado fica sem ele. Como a hora extra, não é filtro. **Histórico e cascata** (2026-10-28): cada PDF da aba Clientes (simplificado ou detalhado) baixado com **um cliente só** entra no Histórico **de quem o baixou**: a aba "Histórico", logo depois da Clientes, lista os 200 mais recentes da pessoa (quando, o cliente, o período, o tipo) com "Gerar de novo", que baixa o mesmo PDF com os mesmos filtros e o período em datas (um relativo, como o mês atual, vira as datas de então), com os dados de hoje; o arquivo não é guardado. A chave **Cascata**, na aba Clientes (o trilho cinza desligada, verde ligada; `cascata=1` na URL; não é filtro), tira da lista de clientes do filtro os que já tiveram relatório da pessoa **hoje** (no fuso da máquina); amanhã eles voltam. Ligada, tirar a etiqueta do cliente não refaz o relatório: só tira a etiqueta e abre a lista, e o relatório vem com o próximo cliente escolhido. **Clientes geral** (2026-10-28): uma aba logo depois da Clientes (antes do Histórico), sem gráficos e sem a escolha de cliente: só o **período** e o **status** (que abre nos concluídos, como a aba Clientes). Mudar um deles não traz números; o botão **Gerar** traz, um embaixo do outro e pelo nome, o relatório detalhado de **cada cliente com horas no período** ("Sem cliente" fica de fora): os cartões da aba Clientes (horas, no plano, excedentes, tarefas, registrados, concluídos) e a tabela das tarefas (o dia, o chamado, no plano, excedente e o tempo) com o total. Cada cliente tem o botão do **PDF detalhado** dele, o mesmo da aba Clientes com ele no filtro, que entra no Histórico; **Baixar todos os PDFs** baixa, num ZIP, o de cada cliente gerado (cada um vai para a auditoria e o Histórico, como baixado sozinho). Na impressão, cada cliente começa numa página. O PDF com um cliente só (desta aba, da aba Clientes ou do Histórico) sai com o nome do cliente no arquivo ("Mercado Bom Preço - relatorio-2026-10-01-a-2026-10-31.pdf").

## 14.8 Relatórios personalizados (pedido do usuário, 2026-10-24)

Evolução da §14.7: abas prontas feitas de blocos, filtros avançados, comparação, detalhar e exportação CSV.

**Simplificação (pedido do usuário, 2026-10-28):** saíram os modelos pessoais e tudo o que só existia para eles: o editor (Salvar como modelo, Editar modelo, Salvar e Restaurar filtros, Excluir), o modelo inicial, o Organizar abas, o relatório para o cliente e os ajustes que só o editor oferecia (mapa de calor, barras + linha, colunas empilhadas, área, linha de referência, número grande, cor, largura e altura do bloco, casas decimais e formato das horas do bloco, período e filtro próprios do bloco, média dos tempos, colunas da lista, ordem das linhas, esconder "Outros", PDF deitado com título e rodapé livres, os agrupamentos por mês, dia da semana e hora, e as medidas % de hora extra, horas por chamado, taxa de conclusão e tarefas por dia útil). As tabelas `report_models` e `report_preferences` saíram na migração `0044`. **Um relatório novo é uma aba pronta escrita no código** (`builder.BUILTINS`), feita sob pedido; o que ela precisar e o motor não tiver entra junto.

### 14.8.1 Abas prontas

As abas de Relatórios, nesta ordem: **Produtividade**, **Clientes** (com a Clientes geral e o Histórico logo depois, §14.7), **Horas extras** e **Chamados** (os indicadores da §14.3: contagens, tempos, reabertura, registrados e concluídos por semana, em aberto por idade e por status, e por grupo). Cada uma é uma lista de blocos (§14.8.3) e tem uma descrição, do catálogo de idiomas, na dica da aba e abaixo do cabeçalho do PDF. Nada é guardado: tudo é calculado de novo com a permissão de quem está vendo ("Quem vê o quê", §14.7).

- **Período:** relativo (semana atual, semana anterior, mês atual, mês anterior, últimos 7, 30 ou 90 dias, últimos N dias, trimestre atual, trimestre anterior, ano até hoje, ano anterior, últimos 12 meses), um dos últimos 12 meses ou duas datas. Até 366 dias. A semana vai de segunda a domingo e, como o mês e o trimestre, até o último dia; os últimos 12 meses são o mês atual e os 11 anteriores, inteiros; os últimos N dias (N de 1 a 366, padrão 30, num campo que só aparece com essa opção) terminam hoje. Sem período na URL, o mês atual.
- **Na tela:** o período e os filtros se ajustam na própria tela e ficam na URL. A tela resume o que está filtrado ("Filtrado por", cada valor com um × que o tira) e tem **Limpar filtros**, que mantém a aba e o período. Setas ao lado do período andam para o anterior e o seguinte, do mesmo tamanho (no "ano até hoje", as mesmas datas do ano vizinho), sem passar de hoje; o personalizado tem atalhos (esta semana, semana passada, este mês, mês passado). Imprimir a tela pelo navegador sai sem menus, filtros e botões: o título, a aba, o período (e o "Filtrado por", quando há) e os blocos, sempre no tema claro.

### 14.8.2 Filtros

| Filtro | Valores |
|--------|---------|
| **Grupo, pessoa, cliente** | Vários de cada; "Sem cliente" é uma das opções |
| **Status** | Vários (o status atual do chamado) |
| **Papel da pessoa** | Fixo: nas medidas de tarefas, quem fez; nas de chamados, cada responsável |
| **Comparar** | Com o período anterior ou com o mesmo período do ano anterior (ou nada): os cartões mostram a variação e o valor de antes (ex.: "+12% · antes: 40h"; na reabertura, em pontos percentuais), com a seta e a cor da direção boa da medida (verde quando melhora, vermelho quando piora: subir é ruim na hora extra, no em aberto, nos tempos até a conclusão e na reabertura, e bom nos concluídos; horas, tarefas, registrados e cancelados ficam neutros); as tabelas, uma coluna Δ por medida (a mesma variação, vazia sem base); as colunas e a linha por período, a série de antes, mais apagada, alinhada pela posição (1º dia com o 1º dia). As barras ficam sem a série. **Período anterior:** meses inteiros comparam com os meses de antes; "ano até hoje", com as mesmas datas do ano anterior; os demais, com o mesmo número de dias logo antes. **Ano anterior:** meses inteiros, com os mesmos meses (fevereiro inteiro com fevereiro inteiro, de 28 ou 29 dias); semanas inteiras (de segunda a domingo), com as 52 semanas antes, para cada dia cair no mesmo dia da semana; os demais, com as mesmas datas (29 de fevereiro vira 28; se o 29 de fevereiro do ano anterior levasse o período a 367 dias, o fim é cortado no limite de 366). A escolha vale para os cartões, a coluna Δ, a série de antes (com a legenda "Período anterior" ou "Mesmo período do ano anterior"), o intervalo, o PDF e o CSV do bloco (o valor de antes e a variação de cada medida) |

- **Limite de permissão:** grupo e pessoa continuam limitados ao que a pessoa pode ver (403 fora disso).
- **Filtros desligados** (pedido do usuário, 2026-10-28): em Configurações, o admin desliga o período, o grupo, a pessoa, o status e o comparar com (todos ligados por padrão; o cliente fica sempre). Desligado, o campo some da tela de Relatórios para todas as pessoas, e o relatório usa o padrão da aba ou o que vier no endereço, como num link de detalhar; o "Filtrado por" continua mostrando o que está aplicado. A API não muda.

### 14.8.3 Blocos

Cada bloco combina **agrupar por × medida × visual**, de listas fechadas no código (`builder`): cada item tem a sua consulta, e nada vira SQL. A medida define de onde vêm os dados: das tarefas (como na §14.7) ou dos chamados (os indicadores da §14.3).

| Escolha | Opções |
|---------|--------|
| **Agrupar por** | Pessoa, cliente, grupo, status, idade (só do em aberto: até 1 dia, 1 a 3, 3 a 7, mais de 7), dia, semana (de segunda a domingo), ou nada, num cartão |
| **Medidas de tarefas** | Horas, horas extras, tarefas (somadas); horas no expediente (horas − extras), no plano e excedentes do cliente, descontadas e a cobrar (horas − descontadas) (§14.7) |
| **Medidas de chamados** | Registrados, concluídos, cancelados, em aberto no fim (contados); mediana até a conclusão, bruta e líquida (dos concluídos no período); reabertura (% dos concluídos com pelo menos uma reabertura). Sem base (nenhum concluído), a mediana e a porcentagem aparecem como "—". O em aberto não se agrupa por período (é o retrato do fim) |
| **Visual** | Cartões (KPI, com a tendência da medida no período numa linha pequena, por dia ou por semana como os gráficos; o em aberto, que é o retrato do fim, sem ela), barras (agrupam por cadastro ou idade), colunas, linha (agrupa por período), tabela (várias medidas, uma por coluna, com o total), lista de tarefas (todas ou só as com hora extra) |
| **Ajustes** | Só os N maiores, com o resto em "Outros". As linhas vão da maior para a menor pela primeira medida. As horas em `hh:mm`. As barras já mostram o valor na ponta; as colunas e a linha, na dica |

- **Pessoa e chamado:** agrupado por pessoa, um chamado conta para cada responsável (como os concluídos da §14.7), mas o total da tabela e o cartão contam o chamado uma vez.
- **Períodos vazios:** agrupado por dia ou semana, todos os períodos aparecem, mesmo sem nada. Um gráfico por dia de um período de mais de dois meses agrupa por semana (a tabela e o CSV continuam por dia).
- **Tempos pela mediana** (§14.1). **Sem linha de meta:** a §14.1 não tem metas.
- **Grade:** na tela, em duas colunas, os gráficos ocupam meia linha e o resto a linha inteira; o último de uma sequência ímpar de gráficos ocupa a linha inteira, para não sobrar meia linha vazia. O PDF tem uma coluna só.
- **Detalhar ao clicar:** clicar numa barra, coluna, ponto ou linha da tabela aplica aquele valor como filtro (a pessoa, o cliente, o grupo, o status, ou o dia ou a semana como período). Quando troca o período, a tela mostra o período detalhado e um link que volta ao de antes. Não aplicam: "Outros", as idades, alguém que a pessoa não pode filtrar e o status do em aberto (que é o do fim do período, e o filtro é o atual). Clicar num número de uma medida de chamado (cartão, célula ou total da tabela) abre a lista desses chamados dentro de Relatórios (`/relatorios/chamados`), com as mesmas regras do número, as colunas de cada tipo (§14.5) e o CSV; a lista de chamados do sistema não tem os filtros dos relatórios.
- **Lista de tarefas:** quando, pessoa, chamado, tempo e fora do expediente, em páginas de 200; o CSV traz todas, também com o cliente.

### 14.8.4 Exportação CSV

- **Dois tipos:** o CSV de um bloco (a tabela agrupada, como na tela, com o total no fim; ou a lista de tarefas inteira) e o dos dados brutos (a lista de tarefas ou de chamados, com as colunas da §14.5 mais as horas). Todo bloco tem o seu botão de download; na lista de tarefas, a tela mostra 200 por página e o CSV traz todas.
- **Formato:** UTF-8 com BOM, para abrir certo no Excel. Os separadores seguem o idioma: em português, `;` e vírgula decimal. As horas saem em minutos e em horas decimais, para somar na planilha.
- **Expediente** (2026-10-27): as listas de tarefas (a do bloco e a de todas as tarefas da API) terminam com a coluna "Expediente", o expediente usado na hora extra de cada tarefa (o de quem a fez, no dia em que ela terminou: "seg–sex 08:00–18:00"). A lista na tela não tem essa coluna.
- **Injeção de fórmula:** uma célula que começa com `=`, `+`, `-`, `@`, tabulação ou retorno de carro ganha um apóstrofo na frente. Títulos e nomes são texto livre.
- **Visibilidade e auditoria:** valem a mesma visibilidade e o mesmo escopo da tela, e cada download vai para a auditoria (`report.exported`, com o formato).

### 14.8.5 Relatório para o cliente

Saiu em 2026-10-28, com os modelos pessoais (era um tipo de modelo). O que vai para o cliente é o PDF da aba Clientes filtrada por ele (§14.7).

### 14.8.6 PDF da aba

O PDF segue a aba: o cabeçalho, a descrição, o período (e o de comparação), os filtros usados, o expediente usado (quando algum bloco do PDF usa a hora extra) e os blocos na ordem, com os mesmos números e formatos da tela (as listas de tarefas, com as 200 primeiras, a primeira página da tela). Os gráficos são desenhados no próprio ReportLab, em vetor, na cor da instalação. Todas as abas usam este (desde 2026-10-27). O download vai para a auditoria (`report.exported`, com `format=pdf`).

- **Página:** A4 em pé. As colunas das tabelas têm a largura do texto mais longo delas (as estreitas, como datas e horas, ficam com o que precisam; as largas dividem o resto).
- **Título e rodapé:** sem título (o nome da aba não vai para o PDF, desde 2026-10-28); em cada página, embaixo, o "Gerado em…" (sem o nome de quem gerou, desde 2026-10-28) e "Página 2 de 5".
- **Cabeçalho** (2026-10-28): no alto, o logotipo dos relatórios (tela Empresa, separado do logotipo do aplicativo) e, logo à direita dele, os dados da empresa; embaixo do cabeçalho, a descrição e o período, o comparado e os filtros (sem o cliente) numa linha só, e uma linha fina antes do primeiro bloco. Sem logotipo, só os dados; sem os dois, nada. Também no PDF da API.
- **Dados da empresa** (2026-10-28): os cadastrados na tela Empresa, um por linha, só os que tiverem algo: o nome fantasia, a razão social, o CNPJ e o e-mail (o primeiro em destaque, a razão social quando não há nome fantasia). Sem os dados cadastrados, nada. Em todos os PDFs: o da aba e o da API.
- **Tabela em mais de uma página** (2026-10-28): a página seguinte abre com o título dela e "(continuação)", e o cabeçalho das colunas.
- **Um cliente só** (2026-10-28): com um cliente só no filtro da tela, os blocos agrupados por cliente (a tabela, as barras dos maiores) ficam fora do PDF, porque teriam só ele; na tela continuam.

### 14.8.7 Fases

| Fase | Entrega | Tarefa |
|------|---------|--------|
| 1 | CSV das telas atuais (cada tabela e as tarefas brutas), períodos relativos, grupo, pessoa, cliente (com "Sem cliente") e status com vários valores. Sem tabela nova | F2-S8-04 |
| 2 | Construtor guiado com as medidas de tarefas e os registrados e concluídos, modelos pessoais (tabela `report_models`), modelos prontos, modelo inicial, CSV de cada bloco | F2-S8-05 |
| 3 | Medidas de chamados (§14.3), o modelo pronto "Chamados", idade do em aberto, colunas empilhadas, comparação com o período anterior, detalhar ao clicar (com a lista de chamados e o CSV dela) | F2-S8-06 |
| 4 | PDF do modelo com gráficos e relatório para o cliente (prévia na tela e PDF com o logotipo) | F2-S8-07 |
| 2026-10-28 | Simplificação: saem os modelos pessoais, o editor, o relatório para o cliente e os ajustes que só o editor usava; ficam as quatro abas prontas (migração `0044`) | F2-S8-15 |
| Depois | Envio agendado por e-mail, usando o worker e o outbox ([ARCHITECTURE 3.12](../ARCHITECTURE.md)) | — |

## 14.9 Painel do cliente (pedido do usuário, 2026-10-30)

A única tela de quem tem o papel Cliente ([docs/08 §8.2](08-organizacao-e-permissoes.md#82-papéis-globais)), em `/painel`. Só leitura: sem filtros, sem comparar e sem baixar. Os números são da empresa do usuário e do mês atual, no fuso da máquina.

- **Horas:** as **horas do plano** (o contrato do cliente: as horas por mês, ou por ano no contrato anual), as **horas trabalhadas** (todas as tarefas dos chamados da empresa no período) e as **horas excedentes** (o que passa do plano no período: o mesmo que a soma do excedente das tarefas na aba Clientes, §14.7). No contrato anual, o período das três é o ano. No avulso e sem contrato, o plano aparece como "Sem plano", com as horas trabalhadas do mês e sem as excedentes.
- **Chamados do mês:** os registrados no mês, os que tiveram tarefa no mês e os que ainda estão em aberto (Pendente, Aguardando, Entregue), mesmo que sejam de meses anteriores. O total e a quantidade em cada status, todos na ordem das Configurações.
- **Tempo por chamado:** as barras com cada um desses chamados (número e título), o status e o **tempo total** trabalhado nele (de sempre, não só do mês), do mais trabalhado para o menos.
- **Visibilidade:** todos os chamados da empresa, inclusive os de categoria confidencial (a regra 7 do docs/08 §8.4).
