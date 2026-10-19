# 19. Migração da interface para o servidor

Situação em **2026-10-19**. A decisão está no [ADR 0011](adr/0011-interface-web-no-servidor.md), e a estrutura do código na [seção 3.11 do ARCHITECTURE](../ARCHITECTURE.md#311-telas-do-servidor-web-adr-0011). Este documento registra o que já foi feito, **onde a migração parou** e como continuar.

## 19.1 Por que

A SPA em Vue + TypeScript obrigava a manter duas stacks. Cada mudança na API exigia regenerar o cliente TypeScript e passar por vue-tsc, ESLint, Prettier, Vitest e o build do Vite. As telas passam a ser renderizadas pelo próprio FastAPI (Jinja2 + HTMX + Tailwind), como no NetKeep, com uma linguagem só e sem Node. A API JSON (`/api/v1`) continua para integrações e agentes de IA.

## 19.2 Onde parou

| Etapa | Entrega | Estado | Commits |
|-------|---------|--------|---------|
| WEB-01 | Base (Jinja2, HTMX, Tailwind standalone, tema, cores) e telas de login e de senha | feito | `73010c3`, `5194367` |
| WEB-02 | Layout (menu, cabeçalho, menu do usuário) e lista de chamados com as filas | feito | `87a4244`, `5194367` |
| WEB-03 | Registro e detalhe do chamado (tarefas, anexos, Tiptap, ações da lateral) | feito | `bd1614a`, `087d68b` |
| WEB-04 | Administração: clientes, usuários, grupos, setores e Configurações | feito | `073b0f2`, `4a89058`, `a041d99`, `a5776a9` |
| WEB-05 | Relatórios (gráficos em SVG e o PDF) | feito | |
| **WEB-06** | **Troca final**: sai a SPA, o Node e o serviço do Vite | **a fazer: é a próxima** | |

Em 2026-10-19 voltaram três funcionalidades de 2026-10-15 que um push forçado tinha tirado do `main` (`0ca1055`, `19ce9eb` e `3d78a76`, guardadas no tag local `remoto-antes-do-force`): o backend veio como estava (`PUT /tickets/{id}/assignees` e o registro do admin em qualquer grupo ativo), e as telas Vue foram refeitas no servidor (vários responsáveis na lateral do chamado; registro só em grupos ativos). Do `19ce9eb`, só valeu para o servidor o registro sem grupo inativo; o resto era cache da SPA e não precisou ser portado.

**Desde a WEB-05, todas as telas vêm do servidor**, com o mesmo visual. Na SPA sobram só o `ServerView.vue` (recarrega a página nos endereços do servidor), as páginas de erro e a vitrine de desenvolvimento. Os commits `5194367`, `087d68b`, `a5776a9` e parte do `4a89058` e do `a041d99` são correções de uma revisão independente feita a cada etapa (19.6).

## 19.3 Como as duas interfaces convivem até a troca final

- **Desenvolvimento:** o nginx manda `/api/` para o uvicorn e o resto para o Vite. O Vite repassa ao uvicorn os endereços já migrados (`server.proxy` no `frontend/vite.config.ts`, a expressão regular com a lista). A SPA recarrega a página ao navegar para um deles (`ServerView.vue`, rotas com `...SERVIDOR` no `frontend/src/router/index.ts`).
- **Produção:** o uvicorn serve as telas do servidor (registradas antes do catch-all) e, no resto, o `frontend/dist`.
- **Idiomas:** os catálogos continuam em `frontend/src/i18n/*.json`, lidos pelo servidor (`web/i18n.py`), e as chaves novas entram nos dois idiomas.
- **CSS:** `scripts/css.sh` gera `web/static/css/app.css`, que não vai para o git. O `deploy.sh` já o gera.

## 19.4 Roteiro da WEB-05 (relatórios): feito

Como ficou: `web/reports.py` e `templates/reports/` (`index.html` e os gráficos em `_charts.html`). Diferenças em relação ao roteiro abaixo:

- O PDF sai no idioma da pessoa: um link não escolhe o `Accept-Language`, por isso a rota da API ganhou o parâmetro opcional `locale`, e o link o manda.
- O link do PDF só aparece com o relatório na tela (período válido e sem erro da API); senão, o botão fica desabilitado.
- O campo de cliente do macro `client_picker` ganhou `required=False`: sem asterisco e com o X para tirar o cliente.
- Saíram da SPA as views e os componentes de relatórios, o `ClientPicker`, os composables `relatorios.ts` e `clientes.ts` e a chave `relatorios.gerandoPdf`. O `tests/test_spa.py` passou a usar `/sem-acesso`.

O roteiro, como estava. O que existia na SPA: `frontend/src/views/reports/ReportsView.vue` (383 linhas), `components/reports/BarChart.vue` e `ColumnChart.vue` (SVG, uma série, só tokens de cor), `composables/relatorios.ts` e `components/tickets/ClientPicker.vue` (o filtro de cliente). A API é `reports/router.py`: `GET /reports/options`, `GET /reports` e `GET /reports/pdf`. Essas rotas usam `CurrentAuth` e o escopo é decidido no service (`service.resolve`). Por isso a tela **não precisa** de `requires`, mas precisa repassar os filtros como a SPA.

1. `web/reports.py`: `GET /relatorios` com os filtros na URL (período: mês ou datas; grupo, pessoa e cliente), chamando `reports_api.report_options` e `reports_api.report`. O link "Baixar PDF" aponta para a rota da API com os mesmos filtros (é GET e usa o cookie da sessão).
2. `templates/reports/index.html`: totais, abas Produtividade, Clientes e Horas extras (links, como as filas) e tabelas. Os gráficos são SVG gerados no Jinja, num macro que imita o `BarChart`/`ColumnChart`. Use o skill de visualização de dados para cores e marcações.
3. Filtros aplicados ao mudar (`data-envia-ao-mudar`) e o campo de cliente do macro `client_picker` (`_fields.html`), que já busca em `/clientes/opcoes`.
4. Testes em `tests/test_web_reports.py`, com o escopo (quem só vê o próprio trabalho não escolhe pessoa) e o erro da API mostrado na tela.
5. Na SPA: `/relatorios` com `...SERVIDOR` e no proxy do Vite. Saem as views e os componentes de relatórios e o `ClientPicker`, e depois apaga-se o que ficar órfão.

## 19.5 Roteiro da WEB-06 (troca final)

Depois da WEB-05 não sobra tela na SPA. Lista do que muda:

- **Desenvolvimento** (`scripts/instalar-servico-dev.sh`): o nginx manda tudo ao uvicorn, sai o `ticketflow-frontend.service` e fica o `ticketflow-css.service`. **Quem roda o script com sudo e reinicia é o usuário** (CLAUDE.md §0.1).
- **Deploy e verificação:** sai o pnpm do `scripts/deploy.sh` e do `scripts/check.sh` (lint, vue-tsc, vitest, build e a etapa de contrato com o cliente TypeScript). O teste de paridade de chaves de idioma (`frontend/src/i18n/i18n.test.ts`) vai para o pytest.
- **Backend:** os catálogos passam para `backend/src/chamados/web/locales/`, trocando `LOCALES_DIR` em `web/i18n.py`. Saem o `_mount_spa` do `main.py`, a configuração `FRONTEND_DIST` e o `tests/test_spa.py`.
- **Repositório:** sai o diretório `frontend/` inteiro (com `ServerView.vue`, `vite.config.ts`, o tema e a paleta em TypeScript).
- **Documentos:**
  - ARCHITECTURE: seções 1, 2, 4, 5, 7, 8 e as receitas.
  - README, manual do servidor (docs/18) e CHANGELOG.
  - O ADR 0011 passa a "Aceita".
  - O CLAUDE.md fala do Vite, do `pnpm vitest` e do `pnpm typecheck` (§0.1 e §0.3); é do usuário, então a mudança vai como proposta.
- **Fica:** a API JSON e o `chamados openapi`, para integrações. O `scripts/vendor-tiptap.sh` continua sendo o único uso de Node, e só para trocar a versão do Tiptap.

## 19.6 Como foi feito (e como continuar)

- **Uma etapa por vez, com commit na `main`** (CLAUDE.md §0). O `scripts/check.sh` completo roda antes de cada commit.
- **A tela não tem regra:** a rota chama a mesma função da rota da API, ou o service. As rotas de administração da API conferem a permissão numa dependência que não roda nessa chamada direta, e por isso a tela usa `requires(P.X)`. Toda tela nova tem teste que tenta entrar sem a permissão.
- **Revisão a cada etapa:** um agente revisor separado lê o diff, compara com a tela Vue removida (`git show <commit>^:frontend/...`) e testa o JavaScript no jsdom. O jsdom precisa de stubs de `XPathEvaluator` (HTMX) e de `showModal`/`close` (`<dialog>`). **O revisor não usa o banco `chamados_test` ao mesmo tempo que os testes do dia a dia**: dois processos no mesmo banco travam nos `TRUNCATE`. Quando precisar de página renderizada, ela é gerada antes e salva para ele.
- **JavaScript sem build:** `web/static/js/` (`app.js` comum; `chamado.js`, `clientes.js` e `configuracoes.js` por tela), com comportamento por atributos `data-*`. Sem navegador na máquina de desenvolvimento, ele é conferido no jsdom do `frontend/node_modules`, que sai na WEB-06. Depois disso, a cobertura do JavaScript passa a ser dos testes ponta a ponta com Playwright (F1-S5-04, no roadmap).

## 19.7 Pendências e riscos conhecidos

| O quê | Situação |
|-------|----------|
| `ticketflow-css.service` | Ainda não instalado nesta máquina. Até `sudo scripts/instalar-servico-dev.sh`, o CSS é gerado à mão com `scripts/css.sh` depois de mudar templates |
| Editor (menções, imagem colada) sem teste automático | Os testes do Vue saíram com a SPA. Conferido no jsdom; fica para o Playwright |
| Erro 4xx num trecho pedido pelo HTMX | A tela fica como estava, sem aviso. Raro: esses pedidos são só leitura |
| `frontend/dist` antigo em dev | Endereços que o servidor não conhece (ex.: `/chamados/`) são respondidos pelo dist. Um build de antes do `strict`/`sensitive` traria de volta a recarga infinita. Some na WEB-06 |
| Primeiro deploy em produção | Precisa de acesso ao GitHub para baixar o binário do Tailwind (CHANGELOG, docs/18) |
| Templates novos no deploy | Valem assim que o `deploy.sh` termina; o código Python, só depois do restart. Reiniciar logo depois do deploy |
| Select que envia ao mudar, pelo teclado | Status, observadores e "Atribuir a" da lateral do chamado são `<select>` nativos com `data-envia-ao-mudar`. No Chrome (Windows e Linux) e no Firefox, a seta com o campo fechado já troca o valor e envia: no "Atribuir a", a primeira opção é "Todas as pessoas do grupo". Na SPA, a lista do Reka UI só enviava ao escolher. A decidir: botão de confirmar ou enviar só com Enter ou clique |
| Validação dos formulários | O servidor confere tudo. Campo `required` escondido bloqueia o envio no navegador sem avisar (aconteceu nos clientes). Campos de um tipo que não está em uso vão num `<fieldset disabled>` |
