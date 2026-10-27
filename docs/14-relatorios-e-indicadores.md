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
| **Período** | Relativo (semana atual, semana anterior, mês atual, mês anterior, últimos 7, 30 ou 90 dias, últimos N dias, trimestre atual, trimestre anterior, ano até hoje, ano anterior, últimos 12 meses) ou duas datas fixas. Até 366 dias, como hoje |
| **Filtros** | §14.8.2 |
| **Blocos** | Lista ordenada de cartões, gráficos e tabelas (§14.8.3) |
| **Público** | Interno ou cliente (§14.8.5) |

- **Período relativo:** é o que torna um modelo salvo útil. "Horas por cliente, mês anterior" serve todo mês. A semana vai de segunda a domingo e, como o mês e o trimestre, até o último dia; os últimos 12 meses são o mês atual e os 11 anteriores, inteiros; os últimos N dias (N de 1 a 366, padrão 30, num campo que só aparece com essa opção) terminam hoje.
- **Modelos prontos:** Produtividade, Clientes e Horas extras (os painéis da §14.7), Chamados (os indicadores da §14.3: contagens, tempos, reabertura, registrados e concluídos por semana, em aberto por idade e por status, e por grupo) e, quando existirem, os painéis da §14.4. Não podem ser apagados, mas dá para duplicar e ajustar.
- **Modelo inicial:** cada pessoa escolhe qual modelo abre ao entrar em Relatórios.
- **Versão da configuração:** a configuração guarda o número da versão do formato. Assim o formato pode mudar sem quebrar os modelos salvos: um modelo de uma versão antiga é convertido ao abrir e gravado no formato novo quando for salvo de novo. Versão 2 (2026-10-26): `compare` deixou de ser sim ou não e passou a ser nada, o período anterior ou o ano anterior (o "sim" da versão 1 é o período anterior).
- **Na tela (fase 2):** os modelos prontos e os da pessoa são as abas de Relatórios. **Salvar como modelo** cria um modelo com os blocos da aba aberta e o período e os filtros da tela; **Editar modelo** muda o nome, o formato das horas, o modelo inicial e os blocos; cada bloco mostra a prévia, com o período e os filtros da tela (modelo novo) ou os salvos (ao editar), e uma combinação sem sentido mostra o erro no lugar dela. O período e os filtros se ajustam na própria tela: num modelo da pessoa, mexer neles mostra **Salvar filtros** e **Restaurar filtros salvos**. A tela resume o que está filtrado ("Filtrado por", cada valor com um × que o tira) e tem **Limpar filtros**, que mantém a aba e o período. Setas ao lado do período andam para o anterior e o seguinte, do mesmo tamanho (no "ano até hoje", as mesmas datas do ano vizinho), sem passar de hoje; o personalizado tem atalhos (esta semana, semana passada, este mês, mês passado). Imprimir a tela pelo navegador sai sem menus, filtros e botões: o título, o modelo, o período (e o "Filtrado por", quando há) e os blocos, sempre no tema claro.
- **Apagar:** é de verdade (nada aponta para um modelo), com confirmação. Até 50 modelos por pessoa, com nomes que não se repetem.

### 14.8.2 Filtros

| Filtro | Valores |
|--------|---------|
| **Grupo, pessoa, cliente** | Vários de cada; "Sem cliente" é uma das opções |
| **Status** | Vários (o status atual do chamado) |
| **Categoria, tipo** | Vários de cada; entram quando a tela de chamado deixar escolhê-los (hoje não deixa, e todo chamado é "incidente" sem categoria) |
| **Situação do chamado** | Aberto, concluído, cancelado. Não entrou: o filtro de status já escolhe os status de cada situação, e as medidas de chamado já separam registrados, concluídos, cancelados e em aberto |
| **Papel da pessoa** | Quem fez a tarefa ou quem é responsável pelo chamado. Fixo: nas medidas de tarefas, quem fez; nas de chamados, cada responsável (a escolha foi descartada pelo usuário em 2026-10-26) |
| **Só hora extra** | Na fase 2, uma opção do bloco "lista de tarefas" (os outros blocos já têm a medida "horas extras") |
| **Comparar** | Com o período anterior ou com o mesmo período do ano anterior (ou nada): os cartões mostram a variação e o valor de antes (ex.: "+12% · antes: 40h"; na reabertura, em pontos percentuais), com a seta e a cor da direção boa da medida (verde quando melhora, vermelho quando piora: subir é ruim na hora extra, no em aberto, nos tempos até a conclusão e na reabertura, e bom nos concluídos; horas, tarefas, registrados e cancelados ficam neutros); as tabelas, uma coluna Δ por medida (a mesma variação, vazia sem base); as colunas e a linha por período, a série de antes, mais apagada, alinhada pela posição (1º dia com o 1º dia). Barras e colunas empilhadas ficam sem a série. **Período anterior:** meses inteiros comparam com os meses de antes; "ano até hoje", com as mesmas datas do ano anterior; os demais, com o mesmo número de dias logo antes. **Ano anterior:** meses inteiros, com os mesmos meses (fevereiro inteiro com fevereiro inteiro, de 28 ou 29 dias); semanas inteiras (de segunda a domingo), com as 52 semanas antes, para cada dia cair no mesmo dia da semana; os demais, com as mesmas datas (29 de fevereiro vira 28; se o 29 de fevereiro do ano anterior levasse o período a 367 dias, o fim é cortado no limite de 366). A escolha vale para os cartões, a coluna Δ, a série de antes (com a legenda "Período anterior" ou "Mesmo período do ano anterior"), o intervalo, o PDF e o CSV do bloco (o valor de antes e a variação de cada medida). Fica salva com o período |

- **Limite de permissão:** grupo e pessoa continuam limitados ao que a pessoa pode ver (403 fora disso).
- **Filtro que deixou de valer:** se um modelo salvo traz um grupo ou uma pessoa que saiu do alcance de quem o abre (ex.: deixou de ser supervisor), a tela avisa qual filtro não vale mais e não mostra só um erro.

### 14.8.3 Construtor guiado

Cada bloco combina **agrupar por × medida × visual**. A medida define de onde vêm os dados: das tarefas (como na §14.7) ou dos chamados (os indicadores da §14.3).

| Escolha | Opções |
|---------|--------|
| **Agrupar por** | Pessoa, cliente, grupo, status, idade (só do em aberto: até 1 dia, 1 a 3, 3 a 7, mais de 7), dia, semana (de segunda a domingo), mês, dia da semana, hora do dia (ou nada, num cartão). Categoria e tipo, quando a tela de chamado os usar (§14.8.2) |
| **Medidas de tarefas** | Horas, horas extras, tarefas (somadas) |
| **Medidas de chamados** | Registrados, concluídos, cancelados, em aberto no fim (contados); mediana até a conclusão, bruta e líquida (dos concluídos no período); reabertura (% dos concluídos com pelo menos uma reabertura). Sem base (nenhum concluído), a mediana e a porcentagem aparecem como "—". O em aberto não se agrupa por período (é o retrato do fim) |
| **Medidas derivadas** | Uma conta entre duas somas, em cada linha e no total; sem base (o divisor zero), "—". **% de hora extra:** horas extras ÷ horas (subir é ruim). **Horas por chamado:** horas ÷ chamados distintos com tarefa no período (neutra). **Taxa de conclusão:** concluídos ÷ registrados no período (subir é bom); passa de 100% quando se conclui mais do que se registra, e o cartão diz isso ("Acima de 100%: concluiu mais do que registrou"). **Tarefas por dia útil:** tarefas ÷ dias do expediente no período (sem os feriados; num período que ainda não acabou, como o mês atual, só os dias até hoje; neutra), com uma casa; não se agrupa por período, dia da semana nem hora. As porcentagens comparam em pontos. Em "Outros", as horas por chamado ficam "—" (um chamado pode estar em duas linhas) |
| **Visual** | Cartões (KPI, com a tendência da medida no período numa linha pequena, por dia ou por semana como os gráficos; o em aberto, que é o retrato do fim, sem ela), barras (agrupam por cadastro ou idade), colunas, colunas empilhadas (as horas no expediente embaixo e as extras em cima), linha (agrupa por período), tabela (várias medidas, uma por coluna, com o total), mapa de calor (dia da semana × hora, uma medida), barras + linha (duas medidas da mesma unidade), lista de tarefas |
| **Ajustes** | Título do bloco (vazio: um automático, como "Horas por pessoa") · só os N maiores, com o resto em "Outros" · ordem (maior, menor, nome) · horas em `hh:mm` ou em decimal (`7,5 h`), para o modelo todo. As barras já mostram o valor na ponta; as colunas e a linha, na dica |

- **Pessoa e chamado:** agrupado por pessoa, um chamado conta para cada responsável (como os concluídos da §14.7), mas o total da tabela e o cartão contam o chamado uma vez.
- **Mapa de calor:** o único bloco com dois agrupamentos: uma linha por dia da semana e uma célula por hora, com as mesmas regras do dia da semana e da hora (abaixo). A cor é uma escala de cinco tons do matiz da cor da instalação (o mais forte, a própria cor principal; sem nada, a célula vazia, só com a borda): cada tom vai até um quinto do maior valor, arredondado para cima, e a legenda mostra esses limites (com poucos valores, ex.: no máximo 2 tarefas numa hora, só os limites que existem). A dica de cada célula diz o dia, a hora e o valor; o leitor de tela lê a mesma grade numa tabela (a grade fica escondida dele, para não ouvir os 168 valores duas vezes). O CSV traz uma linha por dia e hora; o PDF desenha o mapa em vetor, com os mesmos tons. Sem comparar e sem detalhar.
- **Dia da semana e hora do dia:** no fuso da máquina, os 7 dias (de segunda a domingo) e as 24 horas, todos, na ordem, mesmo sem nada. As horas e as tarefas contam na hora e no dia em que a tarefa terminou (`done_at`, a mesma regra do dia; não são distribuídas pelo intervalo que a tarefa atravessa); os chamados, na do registro, da conclusão ou do cancelamento. Em colunas, colunas empilhadas e tabela (as barras ficam para os cadastros e a linha, para os períodos); sem Em aberto (retrato do fim), sem "só os N maiores" e sem detalhar (não há filtro por dia da semana nem por hora). Comparando, a série de antes se alinha pelo mesmo dia da semana ou pela mesma hora.
- **Períodos vazios:** agrupado por dia, semana ou mês, todos os períodos aparecem, mesmo sem nada. Um gráfico por dia de um período de mais de dois meses agrupa por semana (a tabela e o CSV continuam por dia).

- **Sem linha de meta:** a §14.1 não tem metas. A **linha de referência** é outra coisa: nas colunas e na linha, uma linha tracejada na média ou na mediana dos próprios pontos (os sem base ficam de fora), com o nome e o valor ao lado da legenda ("Média: 7h30"), também no PDF.
- **Número grande:** uma opção dos cartões com uma medida só: o número em destaque, com a variação (ao comparar) e a tendência mais alta; no PDF, o número maior. O CSV é o do cartão.
- **Barras + linha:** duas medidas da mesma unidade (horas com horas, contagens com contagens, porcentagens com porcentagens), no mesmo eixo, sem eixo duplo: as colunas da primeira na cor da instalação e a linha da segunda na segunda cor dos gráficos, com a legenda; agrupa por período, dia da semana ou hora (a linha liga pontos em ordem). Sem a série de antes ao comparar (já são duas séries). O editor só oferece para a linha as medidas da mesma unidade das barras.
- **Área:** uma opção da linha, que preenche a área sob ela na cor da série, bem clara (também no PDF).
- **No CSV:** a área e a linha de referência não entram (o CSV traz os pontos; a média e a mediana saem deles).
- **Tempos pela mediana:** a média aparece só como informação secundária (§14.1): uma opção explícita do bloco, só nos dois tempos até a conclusão, e o nome da medida passa a dizer "Média até a conclusão" (na tela, no CSV e no PDF). Nas medidas que somam não há média nem soma a escolher: elas já somam, e somar um tempo ou uma porcentagem não tem sentido; as médias úteis são as derivadas (horas por chamado, tarefas por dia útil).
- **Detalhar ao clicar:** clicar numa barra, coluna, ponto ou linha da tabela aplica aquele valor como filtro (a pessoa, o cliente, o grupo, o status, ou o dia, a semana ou o mês como período). Quando troca o período, a tela mostra o período detalhado e um link que volta ao de antes. Não aplicam: "Outros", as idades, alguém que a pessoa não pode filtrar e o status do em aberto (que é o do fim do período, e o filtro é o atual). Clicar num número de uma medida de chamado (cartão, célula ou total da tabela) abre a lista desses chamados dentro de Relatórios (`/relatorios/chamados`), com as mesmas regras do número, as colunas de cada tipo (§14.5) e o CSV; a lista de chamados do sistema não tem os filtros dos relatórios.
- **Catálogo fechado:** as medidas e os agrupamentos são uma lista fixa no código, e cada item tem a sua consulta. Nada do que a pessoa escolhe vira SQL.

**Ajustes por bloco** (extensão 4, 2026-10-27). Cada um tem um padrão que reproduz o bloco de antes, e os modelos salvos abrem sem conversão (versão 2):

- **Período do bloco:** o da tela (padrão) ou um relativo da lista do §14.8.1 (inclusive os últimos N dias), que anda com o calendário: as setas da tela não o mexem. A comparação da tela vale sobre ele (o período anterior ou o mesmo do ano anterior do período do bloco). O subtítulo do bloco diz o nome do período e as datas.
- **Filtro do bloco:** grupo, pessoa, cliente (com "Sem cliente") e status, com as mesmas etiquetas da tela, numa seção recolhida do editor. Só restringe o filtro da tela, campo a campo: com valores nos dois, vale o que eles têm em comum; só num, esse. Sem nada em comum num campo, o bloco não consulta e mostra "O filtro deste bloco (Pessoa: Ana) não combina com o da tela." (na tela, na prévia e no PDF; sem CSV). O filtro do bloco tem o mesmo limite de permissão da tela: o editor não salva um grupo ou uma pessoa fora do alcance (403), e um que saiu do alcance depois fica de fora, com o aviso no bloco (também no subtítulo dele no PDF), como os filtros salvos do modelo: se um campo do filtro do bloco perde todos os valores, vale o da tela nesse campo. O subtítulo diz o filtro do bloco.
- **Largura e altura:** na grade de duas colunas da tela, a largura é automática (os gráficos em meia linha, o resto na linha inteira, e o último de uma sequência ímpar de gráficos na linha inteira, para não sobrar meia linha vazia), meia linha ou a linha inteira; a escolhida vale mais que a regra (um bloco de meia linha conta na sequência, mas não cresce). A altura (baixa, média ou alta; a média é a de sempre) vale nas colunas, colunas empilhadas, linha, barras + linha e no mapa de calor; as barras crescem com as linhas. No PDF vale a altura, na mesma proporção; a largura não, porque o PDF tem uma coluna só.
- **Cor da série:** nas barras, colunas e linha (de uma série só), a cor da instalação (padrão) ou uma das outras cores dos gráficos (a segunda, a terceira, a quarta), derivadas das cores da instalação com 3:1 sobre o fundo e distintas da principal e entre si, duas a duas, também para quem não enxerga vermelho ou verde. O bloco guarda o nome da cor, não o valor: trocar as cores da instalação muda o bloco junto. A série de antes (comparar) continua a mesma; as colunas empilhadas e as barras + linha mantêm as duas cores delas. O PDF usa a mesma cor (a do modo claro); o CSV não tem cor.
- **Formato das horas e casas decimais:** o bloco pode trocar o formato das horas do modelo (`hh:mm` ou decimal; vazio, o do modelo), nas medidas de horas e na lista de tarefas, e escolher as casas decimais (0, 1 ou 2, fixas; vazio, as de sempre: até duas nas horas em decimal, sem zeros no fim, e uma nas porcentagens e nas taxas) das horas em decimal, das porcentagens e das taxas. Os eixos dos gráficos seguem o mesmo formato. O CSV continua com as horas em decimal (duas casas) e em minutos, para somar na planilha, mas usa as casas do bloco nas porcentagens e nas taxas; o PDF mostra os mesmos textos da tela.
- **Só os maiores e "Outros":** nas barras, colunas, colunas empilhadas e tabela agrupadas por pessoa, cliente, grupo ou status, os N maiores podem vir sem a linha "Outros". O total da tabela continua sendo o do período inteiro e, sem "Outros", o rodapé diz isso ("Total do período, com todos"; também no CSV e no PDF). Nos agrupamentos fixos (períodos, dia da semana, hora, idade) não há só os maiores: todos aparecem, na ordem. Com as medidas derivadas, as horas por chamado de "Outros" ficam "—" (§14.8.3).
- **Colunas da lista de tarefas:** quando, pessoa, chamado, cliente, grupo, status (o atual do chamado), tempo e fora do expediente, sempre nessa ordem; sem escolha, as de sempre (quando, pessoa, chamado, tempo, fora do expediente; no CSV, também o cliente, como antes). O CSV e o PDF seguem as mesmas colunas (no CSV, o chamado é o número e o título, e os tempos, em horas decimais e em minutos).
- **Ordem das colunas da tabela:** é a ordem das medidas, que o editor muda com as setas de cada medida marcada (uma marcada agora entra no fim); vale também nos cartões, no CSV e no PDF. A ordem das linhas (maior, menor) continua pela primeira medida. Os modelos prontos ficam com a ordem de sempre.
- **No detalhar, no CSV e no PDF:** o detalhar e a lista de chamados de um bloco com período ou filtro próprio levam esse período e o filtro efetivo (o da tela restrito pelo do bloco); o CSV do bloco usa os mesmos; no PDF, o bloco ganha o subtítulo com o período e o filtro próprios (os outros blocos ficam como antes).

### 14.8.4 Exportação CSV

- **Dois tipos:** o CSV de um bloco (a tabela agrupada, como na tela, com o total no fim; ou a lista de tarefas inteira) e o dos dados brutos (a lista de tarefas ou de chamados, com as colunas da §14.5 mais as horas). Todo bloco tem o seu botão de download; na lista de tarefas, a tela mostra 200 por página e o CSV traz todas.
- **Formato:** UTF-8 com BOM, para abrir certo no Excel. Os separadores seguem o idioma: em português, `;` e vírgula decimal. As horas saem em minutos e em horas decimais, para somar na planilha.
- **Injeção de fórmula:** uma célula que começa com `=`, `+`, `-`, `@`, tabulação ou retorno de carro ganha um apóstrofo na frente. Títulos e nomes são texto livre.
- **Visibilidade e auditoria:** valem a mesma visibilidade e o mesmo escopo da tela, e cada download vai para a auditoria (`report.exported`, com o formato).

### 14.8.5 Relatório para o cliente

O modelo de público "cliente" é feito para enviar ao cliente, em PDF.

- **No editor:** "Público: cliente" (o padrão é interno). Os blocos ficam escondidos e guardados, para quando o modelo voltar a ser interno; a tela mostra a prévia do que vai no PDF. A prévia tem cara de folha A4 (papel branco também no modo escuro, a tipografia do PDF), com os mesmos textos e a mesma ordem, mas sem prometer as quebras de página.
- **Um cliente:** o filtro precisa ter exatamente um cliente; sem isso, a tela avisa e não há PDF.
- **Cabeçalho:** o logotipo da instalação (Configurações), o nome do cliente e o período.
- **Conteúdo:** totais (horas, chamados registrados e concluídos) e a lista dos chamados do período (os que tiveram tarefa no período, ou foram registrados ou concluídos nele), com número, título, registrado em, concluído em (se está concluído), status atual e as horas das tarefas do período.
- **Quem atendeu:** opcional no modelo, desligado por padrão; são os responsáveis do chamado (o principal e os outros).
- **Rodapé:** só a data em que foi gerado, sem o nome de quem gerou.
- **Fica de fora:** o texto das tarefas (do chamado aparece só o título, porque as tarefas podem ter anotações internas), o valor por hora, as horas extras, os grupos e qualquer outra informação de organização interna.

### 14.8.6 PDF do modelo

O PDF segue o modelo: título, período (e o de comparação), filtros usados e os blocos na ordem, com os mesmos números e formatos da tela (as listas de tarefas, com as 200 primeiras, a primeira página da tela). Os gráficos são desenhados no próprio ReportLab, em vetor, na cor da instalação. Os modelos prontos de horas da §14.7 continuam com o PDF de hoje; o modelo pronto Chamados e os da pessoa usam este. O download vai para a auditoria (`report.exported`, com `format=pdf`).

### 14.8.7 Fases

| Fase | Entrega | Tarefa |
|------|---------|--------|
| 1 | CSV das telas atuais (cada tabela e as tarefas brutas), períodos relativos, grupo, pessoa, cliente (com "Sem cliente") e status com vários valores. Sem tabela nova | F2-S8-04 |
| 2 | Construtor guiado com as medidas de tarefas e os registrados e concluídos, modelos pessoais (tabela `report_models`), modelos prontos, modelo inicial, CSV de cada bloco | F2-S8-05 |
| 3 | Medidas de chamados (§14.3), o modelo pronto "Chamados", idade do em aberto, colunas empilhadas, comparação com o período anterior, detalhar ao clicar (com a lista de chamados e o CSV dela) | F2-S8-06 |
| 4 | PDF do modelo com gráficos e relatório para o cliente (prévia na tela e PDF com o logotipo) | F2-S8-07 |
| Depois | Envio agendado por e-mail, usando o worker e o outbox ([ARCHITECTURE 3.12](../ARCHITECTURE.md)) | — |
