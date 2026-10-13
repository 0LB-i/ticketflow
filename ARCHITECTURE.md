# Arquitetura do TicketFlow

Guia da **estrutura do código como ela é hoje**: onde fica cada coisa, como as peças conversam e quais regras não podem ser quebradas. Leia antes de mexer no projeto e atualize este documento quando a estrutura mudar (módulo novo, camada nova, regra nova).

- **Por que** cada tecnologia foi escolhida e o que está **planejado** para depois: [docs/03-arquitetura.md](docs/03-arquitetura.md) e os [ADRs](docs/adr/).
- **O que** o sistema faz (regras de negócio): [docs/08](docs/08-organizacao-e-permissoes.md), [docs/10](docs/10-chamados.md) e os demais documentos em [docs/](docs/).
- **Em que ponto está** cada item do roadmap: [TAREFAS.md](TAREFAS.md).

Situação em 2026-10-13: Fase 0, Sprint 2, Sprint 3, as Configurações (F1-S3-11), o cadastro de clientes (ligado aos chamados) e, da Sprint 4, as filas, a busca e o "Pegar o próximo" prontos. A seção 10 lista o que ainda não existe.

---

## 1. Visão geral

```
navegador ── HTTPS ──► nginx ──► uvicorn (sistema-chamados.service) ──► PostgreSQL 17 (ou 16)
                                   │
                                   ├─ /api/*  API REST (FastAPI)
                                   └─ /*      interface web compilada (frontend/dist)
```

- **Um processo**, um **monólito modular** em Python (FastAPI). Ele serve a API e também a interface web (SPA em Vue) compilada, **na mesma origem**: sem CORS e com o cookie de sessão funcionando sem configuração extra ([ADR 0010](docs/adr/0010-producao-systemd.md)).
- **Um banco**, o PostgreSQL, que guarda tudo: dados, sessões, auditoria, histórico, configurações e o logotipo. Não há Redis, fila externa nem armazenamento de objetos.
- **API-first:** a interface só conversa com a API; toda regra de negócio e toda decisão de permissão ficam no backend.
- **Uma instalação por empresa** ([ADR 0005](docs/adr/0005-instalacao-por-empresa.md)): não existe `tenant_id`.

Ainda **não existem** o worker (fila de tarefas e e-mails assíncronos) nem o armazenamento de anexos em disco; ambos entram na Sprint 4 (seção 10).

## 2. Mapa do repositório

```
.
├── ARCHITECTURE.md        este guia
├── README.md              apresentação e "como rodar"
├── CLAUDE.md              regras de trabalho (commits na main, não reiniciar o serviço)
├── TAREFAS.md             andamento do roadmap, item a item, com o commit
├── CHANGELOG.md           notas para quem administra uma instalação
├── docs/                  requisitos, regras de negócio, telas, manual do servidor, ADRs
├── backend/               API (Python 3.12, FastAPI, SQLAlchemy 2, Alembic)
│   ├── pyproject.toml     dependências (uv) e configuração de ruff, mypy, pytest, coverage
│   ├── migrations/        Alembic: env.py e versions/0001…0012
│   ├── src/chamados/      código (seção 3)
│   └── tests/             pytest com PostgreSQL real (seção 7)
├── frontend/              interface (Vue 3, TypeScript, Vite, Tailwind 4, Reka UI)
│   ├── public/tema.js     aplica tema, idioma e cores antes da primeira pintura
│   └── src/               código (seção 4)
├── scripts/               check.sh, install-hooks.sh, deploy.sh, backup.sh, instalar-servico-dev.sh
├── deploy/                units do systemd (app, worker, backup) e nginx.conf
└── docker-compose.yml     só desenvolvimento: PostgreSQL 17 e Mailpit
```

Convenção de nomes ([ADR 0001](docs/adr/0001-registro-de-decisoes.md)): **código, banco e API em inglês** (`ticket`, `assignee`); **documentação, mensagens, testes e comentários em português**. No frontend, variáveis e funções de tela também estão em português (`chamado`, `mudarStatus`), enquanto os tipos vindos da API mantêm os nomes em inglês.

---

## 3. Backend (`backend/src/chamados/`)

```
chamados/
├── main.py              create_app(): monta a API em /api/v1 e serve a SPA
├── config.py            Settings (pydantic-settings): variáveis de ambiente e .env
├── cli.py               comando `chamados` (db, admin create, openapi)
├── core/                peças sem domínio, usadas por todos os módulos
│   ├── errors.py        respostas de erro RFC 9457, traduzidas pelo idioma da requisição
│   ├── i18n.py          idiomas (pt-BR, en), Accept-Language e catálogo de mensagens
│   ├── permissions.py   catálogo de permissões, papéis, Actor e can()
│   ├── logging.py       structlog em stdout (journald); json em produção
│   └── health.py        GET /api/health (aplicação + banco)
├── db/
│   ├── base.py          Base declarativa + convenção de nomes das constraints
│   ├── engine.py        engine assíncrona (psycopg 3)
│   ├── session.py       sessão por requisição: dependência DB
│   └── models.py        importa todos os modelos (Alembic e relacionamentos por nome)
└── modules/             um pacote por área de domínio (3.3)
```

### 3.1 Caminho de uma requisição

```
HTTP ─► rota (router.py) ─► dependências ─► service.py / regras ─► modelos SQLAlchemy ─► PostgreSQL
            │                  │
            │                  ├─ DB: AsyncSession da requisição (db/session.py)
            │                  ├─ CurrentAuth: sessão + usuário + Actor (identity/deps.py)
            │                  └─ require(P.X): permissão global exigida pela rota
            └─ schemas Pydantic na entrada e na saída (response_model)
```

1. `main.create_app()` cria a aplicação, registra os tratadores de erro, inclui os routers de cada módulo sob `/api/v1`, devolve 404 em JSON para qualquer `/api/*` desconhecido e, por último, serve `frontend/dist` (rotas desconhecidas devolvem o `index.html`, para o roteamento da SPA).
2. **Autenticação** (`identity/deps.py`, `get_auth`): lê o cookie de sessão, confere o CSRF em métodos que alteram dados, **relê o usuário e os grupos a cada requisição** (mudanças de papel valem na hora) e monta o `Actor`. Com a senha provisória (`must_change_password`), só três rotas funcionam até a troca.
3. **Rota → service:** rotas simples (cadastros) fazem o trabalho no próprio `router.py`; quando há regra de negócio, a rota delega a um `service.py`. Não existe camada de *repository*: os services usam o SQLAlchemy diretamente.
4. **Transação:** cada operação faz um único `commit` no fim. Histórico (`ticket_events`) e auditoria (`audit_log`) entram na **mesma transação** da mudança.
5. **Erros:** qualquer `HTTPException(status, "mensagem em português")` vira Problem Details (`{"type", "title", "status", "detail"}`) em `core/errors.py`, com `title` e `detail` traduzidos para o idioma do `Accept-Language` (3.6). Erros de validação viram 422 com a lista `errors`; exceções não tratadas viram 500 e vão para o log.

### 3.2 Configuração (`config.py`)

Variáveis de ambiente (em produção, `/etc/sistema-chamados/env`; em desenvolvimento, `backend/.env`):

| Variável | Padrão | Uso |
|----------|--------|-----|
| `DATABASE_URL` | `postgresql+psycopg://chamados:chamados@localhost:5432/chamados` | Banco |
| `LOG_LEVEL`, `LOG_FORMAT` | `INFO`, `json` | Logs (`console` em desenvolvimento) |
| `APP_BASE_URL` | `http://localhost:5173` | Endereço usado nos links dos e-mails |
| `COOKIE_SECURE` | `true` | Cookie só em HTTPS (desligar sem HTTPS) |
| `SESSION_IDLE_HOURS`, `SESSION_MAX_DAYS` | `8`, `7` | Expiração das sessões |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_STARTTLS`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | sem `SMTP_HOST` | Sem SMTP, os e-mails vão para o log |
| `FRONTEND_DIST` | `frontend/dist` | Pasta da SPA compilada |

### 3.3 Módulos

| Módulo | Arquivos | Responsabilidade | Rotas |
|--------|----------|------------------|-------|
| `identity` | `models` (User, UserSession, AuthToken), `router` (login, `/me`), `admin_router` (usuários), `deps`, `sessions`, `passwords`, `tokens`, `ratelimit`, `service` (convites e e-mails), `schemas` | Login, sessões e CSRF, senhas (Argon2id), convite e redefinição, força bruta, usuários, idioma da pessoa | `/auth/*`, `/me`, `/users` |
| `organization` | `models` (Role, Team, TeamMember, Department), `router` | Papéis, grupos e membros, setores atendidos | `/teams`, `/departments` |
| `catalog` | `models` (Category, TicketStatus, ResolutionCode), `router` | Árvore de categorias (até 3 níveis; sem tela desde que saíram dos chamados), status por `kind`, códigos de resolução | `/categories`, `/statuses`, `/resolution-codes` |
| `clients` | `models` (Client), `router`, `documents` (CPF, CNPJ alfanumérico, telefone, CEP) | Cadastro de clientes pessoa física e jurídica, com contato e endereço; sem exclusão (inativa) | `/clients` |
| `tickets` | `models`, `schemas`, `router`, `service`, `rules`, `visibility` | Chamados, comentários, observadores, atribuição, transferência, transições e histórico | `/tickets/*` |
| `system` | `models` (SystemSetting), `router`, `service` | Configurações da instalação: idioma padrão, cores, logotipo; idioma efetivo de um usuário | `/branding`, `/admin/settings` |
| `audit` | `models` (AuditLog), `service` (`record()`), `router` | Auditoria de login e administração | `/admin/audit-log` |
| `notifications` | `email` | Envio por SMTP ou para o log (`Mailer`) | — |

Os módulos podem importar modelos e services uns dos outros (por exemplo, `tickets` usa `catalog`, `organization` e `identity`), mas **a decisão de permissão de um chamado só acontece em `tickets`** e **o registro na auditoria só por `audit.service.record()`**.

A lista completa de rotas, com os schemas, está em `/api/docs` (Swagger) e em `frontend/src/api/openapi.json`. As convenções da API (paginação por cursor, `public_id`, Problem Details) estão em [docs/05](docs/05-api.md).

### 3.4 Permissões: três peças

As regras do [docs/08](docs/08-organizacao-e-permissoes.md) estão em três lugares, cada um com um papel:

| Peça | Arquivo | Responde | Usada em |
|------|---------|----------|----------|
| `can(actor, P.X, team_id)` | `core/permissions.py` | "Este papel tem esta permissão (no grupo, se ela depende de supervisão)?" | `require(P.X)` nas rotas de administração; dentro de `allowed_actions` |
| `allowed_actions(actor, TicketState)` | `tickets/rules.py` | "O que esta pessoa pode fazer **neste** chamado agora?" (editar, assumir, transferir, concluir…) | Todo service de chamado (`service.require(auth, ticket, "acao")`) e o campo `allowed_actions` do detalhe |
| `ticket_visibility_filter(actor)` | `tickets/visibility.py` | "Quais chamados esta pessoa vê?" (cláusula SQL) | **Toda** leitura de chamados: lista, detalhe, comentários, histórico |

- `Actor` (dataclass imutável) leva `user_id`, papel, grupos e grupos supervisionados. É montado a cada requisição em `identity/deps.py`.
- As permissões marcadas com 👤 no docs/08 (`SUPERVISOR` em `permissions.py`) valem só para quem supervisiona o grupo do chamado.
- `rules.py` é **puro** (sem banco), por isso os testes são tabelados: perfil × situação → ações esperadas.
- O detalhe responde **403** quando o chamado existe mas não é visível e **404** quando não existe. O acesso de admin ou auditor a um chamado confidencial, fora das regras 1, 3 e 4, vai para a auditoria.
- A interface **nunca decide**: ela só mostra ou esconde botões conforme `allowed_actions` e `me.permissions`.
- **As permissões em vigor vêm do código** (`ROLES` em `core/permissions.py`, pelo código do papel do usuário). A tabela `roles` também guarda a lista de cada papel (cópia gravada pela migração 0002, mais as permissões acrescentadas depois em `NEW_PERMISSIONS` das migrações, como a 0010; um teste confere), mas ainda não é lida: ela prepara os papéis personalizados de depois da v1.0.

### 3.5 Chamados (`modules/tickets/`)

- **Identificação:** `id` interno (bigint), `public_id` (UUID, exposto) e `number` (sequência `ticket_number_seq`, começa em 1000). As rotas aceitam o número ou o UUID (`/tickets/1234`).
- **Status:** a tabela `ticket_statuses` tem um `kind` fixo (`open`, `waiting`, `closed`, `canceled`, `approval`). As regras usam só o `kind`, e cada mudança vai para o status padrão do `kind` de destino.
- **Transições:** `rules.TRANSITIONS` define, para cada ação (`wait`, `resume`, `close`, `reopen`, `cancel`), de quais `kind` se sai, para qual se vai, quem pode e se exige comentário ou código de resolução. O comentário da transição é gravado como comentário do chamado; o de conclusão leva `is_solution`.
- **Prioridade:** `rules.PRIORITY_MATRIX` (impacto × urgência). Forçar outra prioridade exige motivo; `priority: null` volta ao valor da matriz. Por enquanto a interface não mostra impacto nem urgência (ficam 1 × 1, prioridade baixa).
- **Status personalizados:** o admin cria (nome + `kind`: open, waiting, closed, canceled), renomeia, ordena (`PUT /statuses/order`) e remove em Configurações (`admin.settings`). O `kind` não muda depois de criado. Cada `kind` precisa de ao menos um status; ao remover, os chamados vão para o padrão do mesmo `kind`, e se o removido era o padrão o próximo da lista assume. O primeiro status criado de um `kind` vira o padrão. Ações em `audit_log` (`ticket_status.*`).
- **Status no formulário:** além das transições do fluxo, a ação `set_status` (quem tem `ticket.transition` no grupo) escolhe qualquer status no registro (`status_id`, padrão Pendente) e na edição, sem comentário nem código de resolução. `_apply_status` acerta `closed_at` e conta a reabertura ao sair de um `closed`. O evento é `ticket.status_changed` sem `action`.
- **Categoria:** opcional e fora dos formulários do chamado (continua na API e no cadastro). Sem categoria, o grupo é obrigatório e o tipo é `incident`; `category_id: null` no PATCH tira a categoria.
- **Início:** `started_at` é quando o trabalho começou. Sem valor no registro, vale a hora do registro; a pessoa pode informar outra (nunca no futuro, com 5 minutos de folga para o relógio) e alterar depois, com evento no histórico. Na interface, `DateTimeField` acompanha a hora atual até ser mudado.
- **Cliente e contato:** para quem é o trabalho. `client_id` é opcional e só aceita cliente ativo (um cliente inativado depois continua nos chamados antigos); `null` no PATCH tira o cliente. O **contato** (quem pediu) é texto livre e fica em `beneficiary_name`, a antiga "pessoa atendida". Na interface, o `ClientPicker` busca na API de clientes (`client.view`, que todos os papéis têm). O setor atendido (`department_id`) continua na API, mas saiu da interface.
- **Histórico:** cada mudança chama `service.add_event()`, que grava em `ticket_events` com `payload` (antes/depois, com id **e nome** das referências na data do evento). A tabela **só aceita inserção**: uma trigger da migração 0004 recusa `UPDATE` e `DELETE`.
- **Grupos que atuaram:** `ticket_teams` recebe o grupo na criação e a cada transferência; alimenta a regra 2 da visibilidade.
- **Observadores e menções:** `ticket_watchers` (`kind` = `watcher` ou `mentioned`). As menções chegam em `mention_ids`: o texto guarda só "@Nome".
- **Lista:** ordenação padrão (prioridade desc., mais antigo primeiro) com paginação por cursor (base64 de prioridade, data e id). Filtros: `team`, `assignee`, `status` (kinds), `priority` e `q`.
- **Filas:** o parâmetro `view` da lista (`service.view_filter`): `unassigned` (meus grupos, sem responsável, `open`), `mine` (sou o responsável, `open`/`waiting`), `news` (sou o responsável e há novidade), `waiting` (meus grupos, `waiting`), `watching` (sou observador, `open`/`waiting`) e `all` (tudo o que vejo). `GET /tickets/counts` conta as cinco primeiras numa consulta só.
- **Novidade:** comentário de outra pessoa depois da minha última visita (`has_news` em cada item da lista). A visita fica em `ticket_reads` e é gravada pelo `GET /tickets/{id}` (`service.mark_read`). A reabertura exige comentário, por isso também vira novidade.
- **Busca (`q`):** `search_vector` (colunas geradas, índice GIN) em `tickets` (título peso A, descrição peso B) e em `ticket_comments`, na configuração `pt_br` (português sem acentos). Cada palavra vira prefixo (`impress:*`) e todas precisam aparecer. Também acha pelo número (`1234` ou `#1234`), pelo nome do cliente e pelo contato (`unaccent` + `ILIKE`). Passa pelo filtro de visibilidade como qualquer leitura.
- **Pegar o próximo:** `POST /tickets/next` (`service.take_next`) trava o primeiro da fila `unassigned` com `FOR UPDATE SKIP LOCKED` (dois cliques ao mesmo tempo pegam chamados diferentes) e o assume pelo `assign` comum; fila vazia responde 404.

### 3.6 Idiomas (backend)

- Idiomas: `pt-BR` (padrão) e `en` (`core/i18n.py`).
- **Mensagens:** são escritas em português no código. `core/errors.py` traduz `title` e `detail` pelo catálogo `EN` quando o `Accept-Language` pede inglês; a interface envia o idioma escolhido em toda chamada. Um teste percorre o código (AST) e falha se alguma mensagem de `HTTPException` não estiver no catálogo.
- **E-mails:** textos em `identity/service.EMAILS`, por idioma. O idioma é o de quem recebe: `users.locale` ou o padrão do sistema (`system.service.user_locale`).

### 3.7 Configurações (`modules/system/`)

- Tabela `settings` com chave e valor (jsonb). Sem a linha, vale o padrão. Chaves: `locale`, `colors` (`brand`, `neutral`, `background`) e `logo` (imagem em base64, tipo e sha256).
- `GET /branding` é **público**: a tela de login também usa as cores, o logotipo e o idioma.
- O logotipo é servido por `GET /branding/logo?v=<hash>`, com cache permanente (o endereço muda quando a imagem muda). Só PNG, JPEG e WebP, conferidos pelos primeiros bytes; SVG é recusado porque pode conter scripts.
- O backend guarda só as **três cores**; a paleta inteira é derivada no frontend (4.6).

### 3.7.1 Clientes (`modules/clients/`)

- Pessoa física (`person`: CPF, RG, nascimento) ou jurídica (`company`: CNPJ, nome fantasia, inscrições estadual e municipal, pessoa de contato). Os campos do outro tipo ficam nulos.
- Obrigatórios: nome ou razão social, CPF/CNPJ (único), e-mail, telefone e endereço (CEP, logradouro, número, bairro, cidade, UF).
- Documentos, telefones e CEP são gravados sem pontuação; a interface formata (`composables/documentos.ts`). O CNPJ aceita o formato alfanumérico (julho de 2026): mesmo cálculo dos dígitos, com o valor de cada caractere = ASCII − 48.
- A validação fica no router (`_clean`), com mensagens do catálogo de idiomas. O formulário envia o cadastro inteiro (`PUT`).
- Permissões: `client.view` (agente, admin, auditor) e `client.manage` (agente, admin). A auditoria registra só **quais campos** mudaram, sem os dados pessoais.
- Ligação com os chamados: `tickets.client_id` (3.5).

### 3.8 Auditoria × histórico

| | `audit_log` | `ticket_events` |
|--|-------------|-----------------|
| O quê | Login, falhas de login, bloqueios, administração (usuários, grupos, setores, categorias, configurações), acesso a confidencial | Tudo o que acontece **em um chamado** |
| Gravado por | `audit.service.record()` | `tickets.service.add_event()` |
| Lido por | `GET /admin/audit-log` (`audit.view`) | `GET /tickets/{id}/events` (quem vê o chamado) |

### 3.9 Banco e migrações

- **A fonte da verdade do schema são as migrações** (`backend/migrations/versions/`); o [docs/04](docs/04-modelo-de-dados.md) e o `esboco-schema.sql` são o desenho das tabelas que ainda não existem.

| Migração | Conteúdo |
|----------|----------|
| `0001` | Extensões `citext`, `unaccent`, `pg_trgm` e a configuração de busca `pt_br` |
| `0002` | Papéis (com os 3 do sistema), usuários, sessões, tokens de acesso, grupos e membros, setores, auditoria |
| `0003` | Login por nome de usuário, troca obrigatória de senha e administrador padrão `admin`/`admin` |
| `0004` | Categorias, status (os 4 padrão), códigos de resolução, chamados, grupos que atuaram, observadores, comentários, histórico (trigger *append-only*) |
| `0005` | `settings` e `users.locale` |
| `0006` | `tickets.category_id` opcional |
| `0007` | `tickets.started_at` (início do trabalho) |
| `0008` | Status "Entregue" (`closed`, não é o padrão do kind) |
| `0009` | "Aguardando" passa a "Aguardando cliente" |
| `0010` | `clients` e as permissões `client.view`/`client.manage` nos papéis |
| `0011` | `tickets.client_id` (cliente do chamado, opcional) |
| `0012` | `ticket_reads` (última visita, para as novidades) e `search_vector` em `tickets` e `ticket_comments` |

- **Convenções:** `bigint GENERATED ALWAYS AS IDENTITY` + `public_id uuid` nas entidades expostas; `timestamptz` sempre; nomes de constraint previsíveis (`db/base.py`); nada é apagado nos cadastros (só desativado: `is_active`).
- **Compatibilidade:** só recursos do PostgreSQL **16 e 17** (`check.sh --completo` testa nos dois).
- **Nova migração:** gerar com o autogenerate do Alembic a partir dos modelos, **revisar à mão** (sequences, triggers, cargas iniciais e índices parciais não são detectados) e conferir que o `downgrade` funciona. O teste `test_migrations` desce até a base e sobe de novo.

### 3.10 Comando `chamados` (`cli.py`)

| Comando | Faz |
|---------|-----|
| `chamados db upgrade [rev]` / `downgrade rev` / `current` | Migrações |
| `chamados admin create --email … --name …` | Cria um administrador e mostra o link para definir a senha (recuperação de acesso) |
| `chamados openapi [-o arquivo]` | Exporta o contrato OpenAPI (usado pelo `pnpm gen:api`) |

---

## 4. Frontend (`frontend/src/`)

```
src/
├── main.ts              cria a app: Pinia, router, i18n, TanStack Query; carrega /branding e monta
├── App.vue              escolhe o layout, aplica o idioma, trata a sessão expirada
├── api/
│   ├── client.ts        openapi-fetch + middleware (CSRF, Accept-Language, 401) + ou()/mensagemDeErro()
│   ├── openapi.json     contrato exportado do backend      ┐ gerados por `pnpm gen:api`:
│   └── schema.d.ts      tipos TypeScript do contrato       ┘ nunca editar à mão
├── router/index.ts      rotas, meta (publica, permissao, cartao) e o guard
├── stores/              Pinia: auth (usuário logado), branding (cores, logotipo, idioma padrão), theme
├── composables/         consultas e mutações (TanStack Query) e utilidades
│   ├── admin.ts         usuários, grupos, setores, status (admin)
│   ├── chamados.ts      chamados, comentários, histórico, status, pessoas
│   ├── clientes.ts      clientes; documentos.ts formata e valida CPF, CNPJ, telefone e CEP
│   └── formato.ts (datas no fuso de São Paulo), useHead.ts, useToast.ts
├── views/               uma pasta por área: auth/, tickets/, clients/, admin/
├── components/
│   ├── ui/              design system: Button, TextField, SelectField, RadioGroup, DateTimeField, Modal, SidePanel, DataTable, badges…
│   ├── layout/          AppLayout (menu, cabeçalho), SideNav, UserMenu (idioma, sair), ThemeMenu, AppLogo
│   ├── admin/           StatusSettings (status dos chamados, dentro de Configurações)
│   ├── editor/          RichEditor (Tiptap → Markdown, @menções), MarkdownView, markdown.ts
│   └── tickets/         TicketTimeline, CommentBox, TicketDetails, TicketEditPanel, ClientPicker, eventos.ts
├── tema/paleta.ts       paleta derivada das 3 cores, com ajuste de contraste
├── i18n/                index.ts, pt-BR.json, en.json
├── assets/main.css      Tailwind 4 + tokens de cor (--tf-*) dos modos claro e escuro
└── test/setup.ts        montar(), simularApi() e escolher() (opção de Select) para os testes
```

### 4.1 Inicialização

1. `index.html` carrega `public/tema.js` antes de tudo. Ele aplica a classe `dark`, o `lang` e a folha de cores guardada no navegador, para a primeira pintura já sair certa. Fica em arquivo próprio para a Content-Security-Policy não precisar liberar scripts embutidos.
2. `main.ts` instala os plugins e **espera o `GET /branding`** (cores, logotipo, idioma padrão) antes de montar. Se a API não responder, monta com o padrão.
3. Ao ser instalado, o router faz a navegação inicial. O guard (`protegerRota`) carrega o `/me` uma vez e decide: rota pública, login, troca obrigatória de senha, permissão (`meta.permissao`) ou acesso liberado.
4. `App.vue` escolhe o layout (`PublicLayout` para as telas sem login, `AppLayout` para o resto). Também aplica o idioma depois que o `/me` carrega (o da pessoa ou o padrão do sistema) e, se a sessão expira no meio do uso, volta ao login guardando a página.

### 4.2 Dados

- **Cliente:** `api` (openapi-fetch) é tipado pelo `schema.d.ts`. Mudar a API sem regenerar o cliente quebra o `vue-tsc`, e o `check.sh` falha se o cliente gerado não estiver commitado.
- O **middleware** do cliente envia o `X-CSRF-Token` (lido do cookie `tf_csrf`) nas chamadas que alteram dados e o `Accept-Language` com o idioma atual. Num 401 fora de `/auth/*`, dispara o evento de sessão expirada.
- `ou(resultado, mensagemPadrao)` devolve os dados ou lança um `Error` com o `detail` da API, já traduzido pelo backend.
- **Leitura** com TanStack Query: as chaves são `['chamados', filtro]` (uma por fila e filtros), `['chamados', 'contagens']`, `['chamado', numero]`, `['chamado', numero, 'comentarios' | 'eventos']`, `['grupos']`, `['usuarios']`, `['setores']`, `['status']`, `['codigos-resolucao']`, `['clientes', filtro]`, `['cliente', id]`.
- **Escrita:** `useAlteracao(fn, chaves)` (admin) e `useAcaoNoChamado(numero, fn)` (chamados) fazem a mutação e invalidam as chaves afetadas.
- **Usuário logado:** `auth.me` vem do `/me` e guarda os grupos e as permissões. Telas que dependem dos grupos o releem (`auth.carregar()`), porque eles podem mudar depois do login.

### 4.3 Telas

| Rota | Tela | Acesso |
|------|------|--------|
| `/login`, `/esqueci-senha`, `/convite/:token`, `/redefinir-senha/:token` | `views/auth/` | Público |
| `/trocar-senha` | Troca obrigatória da senha provisória | Logado |
| `/chamados` | Filas em abas com contadores (Não atribuídos, Meus, Com novidades, Aguardando, Acompanhando, Todos), filtros de grupo e prioridade (status e responsável na aba Todos), "Pegar o próximo". Aba e filtros na URL (`?aba=todos&grupo=…&prioridade=…&status=…&responsavel=…&q=…`); sem aba, abre em Meus (ou em Todos, para quem não tem grupo). É a tela inicial: `/` redireciona para cá | Logado |
| `/chamados/novo` | Registro | `ticket.create` |
| `/chamados/:numero` | Detalhe: linha do tempo, comentários, ações | Quem vê o chamado (403/404 na própria tela) |
| `/clientes` | Lista com busca (nome, CPF/CNPJ, e-mail) | `client.view` |
| `/clientes/novo`, `/clientes/:id` | Cadastro em três colunas (dados, contato, endereço); sem `client.manage`, só leitura | `client.manage` / `client.view` |
| `/admin/usuarios`, `/admin/grupos`, `/admin/setores` | Cadastros | `admin.users` / `admin.organization` |
| `/admin/configuracoes` | Idioma, cores, logotipo e status dos chamados | `admin.settings` |
| `/dev/componentes` | Vitrine do design system | Só em desenvolvimento |

Os itens do menu lateral (`SideNav.vue`) aparecem conforme `auth.pode(permissão)`. O botão "Novo chamado" e a busca global ficam no cabeçalho (`AppLayout.vue`): `1234` ou `#1234` abre o chamado, texto abre a aba Todos com `q`.

### 4.4 Componentes

- `components/ui/` é o **design system** ([docs/17](docs/17-identidade-visual.md), [ADR 0008](docs/adr/0008-reka-ui.md)): componentes acessíveis sobre o Reka UI e estilizados só com os tokens (`bg-surface`, `text-muted`, `bg-primary`…), **nunca com cores diretas**.
- Telas de administração seguem o mesmo padrão: lista ou árvore, botão **Novo** e edição num `SidePanel`.
- Os componentes de chamado (`components/tickets/`) recebem o chamado por prop e decidem os botões só por `chamado.allowed_actions`.

### 4.5 Editor e Markdown

- Descrição e comentários são **Markdown** no banco. `RichEditor.vue` (Tiptap + `@tiptap/markdown`) edita visualmente e grava Markdown. Com `pessoas`, o `@` abre a lista de colegas, e `mencionados()` devolve os ids para `mention_ids`.
- `MarkdownView.vue` mostra o texto com `markdown-it` em `html: false`: HTML digitado aparece como texto e links `javascript:` são recusados. É o único `v-html` do projeto.
- O Tiptap (~150 kB gzip) fica num pedaço carregado só nas telas de chamado.

### 4.6 Tema e cores

- `assets/main.css` define os tokens `--tf-*` em `:root` (claro) e `.dark` (escuro); o Tailwind os expõe como cores (`@theme inline`). O modo escuro é a classe `dark` no `<html>` (`stores/theme.ts`; escolha do usuário no `ThemeMenu`).
- **Cores personalizadas:** `tema/paleta.ts` deriva os 13 tokens que dependem da identidade a partir das 3 cores das Configurações, em OKLCH, mantendo o matiz e ajustando o tom até cumprir os contrastes da WCAG AA ([docs/17 §17.3](docs/17-identidade-visual.md#173-contraste-wcag-21-aa)). Com as cores padrão, usa a paleta original escolhida à mão (`PALETA_PADRAO`).
- `stores/branding.ts` injeta a folha `<style id="tf-cores">` (`html:root{…}` e `html.dark{…}`, mais específicos que os do `main.css`) e guarda uma cópia no navegador para o `tema.js`.
- Cores de status, prioridade e do botão destrutivo **não** dependem das 3 cores.

### 4.7 Idiomas (frontend)

- `i18n/pt-BR.json` e `i18n/en.json` têm **as mesmas chaves**: o tipo do `createI18n` exige isso, e um teste confere chaves e marcadores (`{nome}`).
- **Nenhum texto fixo** nas telas: tudo via `$t()`/`t()`. Nas mensagens, não use `@` nem `|`, que são sintaxe do vue-i18n.
- `definirIdioma()` troca o idioma da interface, o `lang` do `<html>` e o idioma das chamadas à API. Datas (`formato.ts`) e ordenação alfabética (`compararTexto`) seguem o idioma atual; o fuso é sempre America/Sao_Paulo.

---

## 5. Contrato entre backend e frontend

```
modelos Pydantic (backend) ──chamados openapi──► openapi.json ──openapi-typescript──► schema.d.ts ──► api (openapi-fetch)
```

- Depois de mudar qualquer rota ou schema: `pnpm gen:api` (no `frontend/`) e commitar `src/api/` **junto** com a mudança do backend.
- Campos novos são aditivos. Mudança incompatível só numa nova versão da API (`/api/v2`), conforme o [docs/05](docs/05-api.md).

## 6. Segurança (resumo do que está implementado)

| Tema | Como |
|------|------|
| Senhas | Argon2id; mínimo de 8 caracteres; lista de senhas comuns (`identity/senhas_comuns.txt`) |
| Sessão | Cookie `tf_sessao` (HttpOnly, SameSite=Lax, Secure em produção); só o hash fica no banco; expira por inatividade e por prazo máximo; desativar o usuário encerra as sessões |
| CSRF | Token sincronizado: cookie `tf_csrf` legível pela SPA + header `X-CSRF-Token` conferido com o hash da sessão |
| Força bruta | Limite por IP em memória (a API roda num processo só) + espera progressiva e bloqueio da conta (`ratelimit.py`) |
| Permissões | Sempre no backend (3.4); a interface só esconde botões |
| Conteúdo | Markdown sem HTML bruto; logotipo sem SVG e conferido pelos bytes; `X-Content-Type-Options: nosniff` |
| Cabeçalhos | CSP, HSTS, X-Frame-Options e Referrer-Policy no nginx (`deploy/nginx.conf`) |
| Rastro | `audit_log` e `ticket_events` (só inserção) |

## 7. Testes e verificação

| Onde | Ferramenta | Como |
|------|------------|------|
| `backend/tests/` | pytest + **PostgreSQL real** (`TEST_DATABASE_URL`, banco `chamados_test`) | A sessão de testes desce as migrações até a base e sobe de novo; cada teste começa com `TRUNCATE` (`conftest.py`). Auxiliares: `criar_usuario`, `entrar`, `grupo`, `criar_categoria`, `FakeMailer` |
| Regras puras | pytest parametrizado | `test_permissions` (matriz do docs/08), `test_regras_chamados` (ações × situação), `test_visibilidade` (6 regras) |
| `frontend/src/**/*.test.ts` | Vitest + Vue Test Utils (jsdom) | `montar()` monta com os plugins da app; `simularApi()` substitui o `fetch` e registra as requisições. Com router, simule também o `GET /api/v1/me` (o guard o carrega) |

`scripts/check.sh` faz o papel do CI ([docs/12 §12.3](docs/12-processo-de-desenvolvimento.md#123-verificação-local-no-lugar-do-ci)):

| Modo | Roda |
|------|------|
| `--rapido` (hook de pre-commit) | ruff, ESLint e Prettier nos arquivos do commit; procura segredos |
| padrão | + mypy, pytest com cobertura (mínimo de 80%) no PostgreSQL 17, vue-tsc, Vitest, build e o contrato da API |
| `--completo` | + pytest no PostgreSQL 16 e auditoria de dependências |

## 8. Execução

| Ambiente | Como |
|----------|------|
| **Desenvolvimento, terminais** | PostgreSQL nativo ou `docker compose up -d db`; `uv run uvicorn chamados.main:create_app --factory --reload` (porta 8000) e `pnpm dev` (porta 5173, repassa `/api` para a 8000). Ver o [README](README.md#como-rodar-desenvolvimento) |
| **Desenvolvimento, serviço** | `sudo scripts/instalar-servico-dev.sh`: instala o `sistema-chamados.service` com a unit da produção e um ajuste local (escuta em `0.0.0.0:8000`, sem nginx), compila o frontend e aplica as migrações |
| **Produção** | Ubuntu 24.04, systemd (`deploy/*.service`), nginx com HTTPS, PostgreSQL 17. Atualização por `scripts/deploy.sh`; backup diário por `scripts/backup.sh` (timer). Passo a passo no [manual do servidor](docs/18-manual-do-servidor.md) |

Quem reinicia o serviço é sempre a pessoa responsável, nunca um script ou o Claude Code ([CLAUDE.md](CLAUDE.md)). O frontend compilado é servido direto da pasta e muda na hora; o backend só muda depois do `systemctl restart`.

---

## 9. Regras da arquitetura

1. **Toda leitura de chamados passa por `ticket_visibility_filter`**: nas buscas, nos relatórios, nos anexos, em tudo o que vier.
2. **Toda ação em chamado passa por `allowed_actions`** (`service.require`). Rota nova de chamado sem essa checagem é defeito.
3. **Toda alteração de chamado** (campos, prioridade, status, responsável, grupo, observadores, edição de comentário) **gera um evento** em `ticket_events`, na mesma transação. O histórico nunca é alterado. Os comentários novos já são o próprio registro.
4. **Administração e login vão para o `audit_log`** com antes e depois.
5. **Cadastros não são apagados**, só desativados.
6. **A interface não decide permissões**; usa `allowed_actions` e `me.permissions` só para mostrar botões.
7. **Nada de cor direta** nos componentes: só tokens. Nada de texto fixo: só i18n, nos dois idiomas.
8. **O contrato da API é gerado**: `schema.d.ts` não se edita à mão.
9. **Mensagens de erro da API em português**, com a tradução no catálogo de `core/i18n.py`.
10. **Só SQL que roda no PostgreSQL 16 e 17.**
11. **Migração revisada e reversível**; o schema muda só por migração.

## 10. O que ainda não existe

| Peça | Onde entra | Referência |
|------|------------|------------|
| Worker, fila de tarefas e *outbox* (eventos → notificações) | Comando `chamados worker`; a unit `deploy/sistema-chamados-worker.service` já existe, mas só deve ser instalada quando o comando existir | Sprint 4, [docs/03](docs/03-arquitetura.md#eventos-de-domínio) |
| Notificações por e-mail dos chamados | Hoje só existem os e-mails de convite, redefinição e bloqueio, enviados na hora | Sprint 4 |
| Anexos (upload em duas etapas, disco local) | Módulo `attachments`, `FILES_DIR` | Sprint 4, [docs/11](docs/11-anexos-e-arquivos.md) |
| `ETag` e aviso de colisão | `tickets` | Sprint 4 |
| Status personalizados, ocultar comentário, testes ponta a ponta (Playwright) | — | Sprint 5 |
| Tela da auditoria | A API `GET /admin/audit-log` já existe | Sprint 5 |
| MFA, sessões, aprovações, sino de notificações | — | Fase 2 |
| Tokens de API, webhooks, IA, MCP | — | Depois da v1.0, [docs/06](docs/06-integracao-ia.md) |

## 11. Receitas

**Nova rota de API**
1. Schema de entrada e saída (Pydantic) no módulo; rota no `router.py` com `CurrentAuth` ou `require(P.X)`.
2. Regra de negócio no `service.py`; se for chamado, `service.require(auth, ticket, "acao")` e `add_event()`.
3. Mensagem de erro em português → tradução no catálogo `EN` de `core/i18n.py`.
4. Testes de integração **e de permissão** (quem pode e quem não pode).
5. `pnpm gen:api` e commitar `frontend/src/api/`.

**Nova tabela ou coluna**
1. Modelo em `modules/<módulo>/models.py`; se o módulo é novo, importar em `db/models.py`.
2. Migração por autogenerate, revisada à mão, com `downgrade`.
3. Se a tabela referencia `users` ou `teams`, incluí-la no `TRUNCATE` do `tests/conftest.py`.

**Nova ação num chamado**
1. Incluir a ação em `rules.allowed_actions` (e em `TRANSITIONS`, se mudar o status).
2. Linha nova nos testes tabelados de `test_regras_chamados.py`.
3. Service + rota + evento; frase do evento em `components/tickets/eventos.ts` e nos dois JSON de idioma.

**Nova tela**
1. View em `views/<área>/`; rota em `router/index.ts` com `meta.permissao`; item no `SideNav.vue`, se for de menu.
2. Dados por composable (TanStack Query) e mutações com invalidação das chaves afetadas.
3. Textos em `pt-BR.json` **e** `en.json`; só componentes de `ui/` e tokens de cor.
4. Teste de componente com `montar()` e `simularApi()`.

**Nova permissão**
1. Código em `P` (`core/permissions.py`) e nos papéis (`ROLES`); se depende de supervisão, em `SUPERVISOR`.
2. Migração que atualiza `roles.permissions` dos papéis do sistema, e o teste `test_papeis_da_migracao_batem_com_o_catalogo` passa a comparar com essa migração.
3. Linha nova na matriz de `test_permissions.py` e no [docs/08](docs/08-organizacao-e-permissoes.md#83-catálogo-de-permissões).
