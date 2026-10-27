# Arquitetura do TicketFlow

Guia da **estrutura do código como ela é hoje**: onde fica cada coisa, como as peças conversam e quais regras não podem ser quebradas. Leia antes de mexer no projeto e atualize este documento quando a estrutura mudar (módulo novo, camada nova, regra nova).

- **Por que** cada tecnologia foi escolhida e o que está **planejado** para depois: [docs/03-arquitetura.md](docs/03-arquitetura.md) e os [ADRs](docs/adr/).
- **O que** o sistema faz (regras de negócio): [docs/08](docs/08-organizacao-e-permissoes.md), [docs/10](docs/10-chamados.md) e os demais documentos em [docs/](docs/).
- **Em que ponto está** cada item do roadmap: [TAREFAS.md](TAREFAS.md).

Situação em 2026-10-13: Fase 0, Sprint 2, Sprint 3, as Configurações (F1-S3-11), o cadastro de clientes (ligado aos chamados) e, da Sprint 4, as filas, a busca e os anexos prontos (o "Pegar o próximo" saiu junto com a fila de não atribuídos, em 2026-10-15). A seção 10 lista o que ainda não existe.

Em 2026-10-21 entraram o outbox, a fila de tarefas e o worker (F1-S4-03, seção 3.12) e, por eles, as notificações por e-mail dos chamados (F1-S4-04, 3.13).

Em 2026-10-23 entraram os tokens de API (com a tela Tokens de API e a `Idempotency-Key`, 3.1) e o servidor MCP para assistentes de IA (3.14).

Em 2026-10-17 começou a migração da interface da SPA em Vue para telas renderizadas no servidor, com Jinja2, HTMX e Tailwind ([ADR 0011](docs/adr/0011-interface-web-no-servidor.md)). Em 2026-10-19 ela terminou (WEB-06): todas as telas são do servidor, e saíram o `frontend/`, o Node e o serviço do Vite. O histórico e as pendências estão no [docs/19](docs/19-migracao-da-interface.md); a estrutura, na seção 3.11.

---

## 1. Visão geral

```
navegador ── HTTPS ──► nginx ──► uvicorn (ticketflow.service) ──► PostgreSQL 17 (ou 16)
                                   │
                                   ├─ /api/*    API REST (FastAPI)
                                   ├─ /mcp      servidor MCP para assistentes de IA (modules/mcp_server)
                                   └─ /*        telas do servidor (Jinja2 + HTMX, web/) e /static

chamados worker (ticketflow-worker.service) ──► PostgreSQL: outbox → fila de tarefas, rotinas diárias
```

- **Um programa**, um **monólito modular** em Python (FastAPI), que na produção roda em vários workers do uvicorn. Por isso nada fica na memória de um processo: sessões, presença no chamado e limite de login ficam no banco. Ele serve a API e também a interface web, **na mesma origem**: sem CORS e com o cookie de sessão funcionando sem configuração extra ([ADR 0010](docs/adr/0010-producao-systemd.md)). As telas são renderizadas pelo próprio FastAPI (3.11); não há build de interface nem Node.
- **Um banco**, o PostgreSQL, que guarda tudo: dados, sessões, auditoria, histórico, configurações, o logotipo, o outbox e a fila de tarefas. Não há Redis, fila externa nem armazenamento de objetos.
- **Regras só no backend:** as telas chamam as funções da API ou os services e só montam o HTML; toda regra de negócio e toda decisão de permissão ficam nos módulos.
- **Uma instalação por empresa** ([ADR 0005](docs/adr/0005-instalacao-por-empresa.md)): não existe `tenant_id`.

Os anexos ficam em disco, em `FILES_DIR` (3.5.1). Um segundo processo, o **worker** (`chamados worker`), consome o outbox e a fila de tarefas e roda as rotinas diárias (3.12).

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
│   ├── migrations/        Alembic: env.py e versions/0001…0038
│   ├── src/chamados/      código (seção 3); as telas do servidor ficam em web/ (3.11)
│   ├── tests/             pytest por área: unidade, api, telas, banco, worker (seção 7)
│   └── bench/             benchmark: tempo e precisão com 50 mil chamados (seção 7.1)
├── scripts/               check.sh, install-hooks.sh, deploy.sh, instalar-servico-dev.sh, css.sh,
│                          vendor-tiptap.sh (o único uso de Node, só para trocar a versão do Tiptap),
│                          preparar-maquina-dev.sh (Ubuntu 24.04 novo pronto para desenvolver)
└── deploy/                units do systemd (app e worker) e nginx.conf
```

Convenção de nomes ([ADR 0001](docs/adr/0001-registro-de-decisoes.md)): **código, banco e API em inglês** (`ticket`, `assignee`); **documentação, mensagens, testes e comentários em português**. No JavaScript das telas (`web/static/js/`), variáveis, funções e atributos `data-*` também estão em português (`escolherCliente`, `data-envia-ao-mudar`).

---

## 3. Backend (`backend/src/chamados/`)

```
chamados/
├── main.py              create_app(): monta a API em /api/v1 e as telas do servidor
├── config.py            Settings (pydantic-settings): variáveis de ambiente e .env
├── cli.py               comando `chamados` (db, admin create, attachments purge, worker, openapi)
├── core/                peças sem domínio, usadas por todos os módulos
│   ├── errors.py        respostas de erro RFC 9457, traduzidas pelo idioma da requisição
│   ├── i18n.py          idiomas (pt-BR, en), Accept-Language e catálogo de mensagens
│   ├── permissions.py   catálogo de permissões, papéis, Actor e can()
│   ├── text.py          texto dos formulários: optional_text() e required_text()
│   ├── timezone.py      LOCAL_TZ: o fuso da máquina (TZ ou /etc/localtime; sem eles, UTC)
│   ├── logging.py       structlog em stdout (journald); json em produção
│   └── health.py        GET /api/health (aplicação + banco)
├── db/
│   ├── base.py          Base declarativa + convenção de nomes das constraints
│   ├── engine.py        engine assíncrona (psycopg 3)
│   ├── session.py       sessão por requisição: dependência DB
│   └── models.py        importa todos os modelos (Alembic e relacionamentos por nome)
├── modules/             um pacote por área de domínio (3.3)
└── web/                 telas renderizadas no servidor: Jinja2, HTMX, Tailwind (3.11)
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

1. `main.create_app()` cria a aplicação, registra os tratadores de erro, inclui os routers de cada módulo sob `/api/v1`, devolve 404 em JSON para qualquer `/api/*` desconhecido e, por último, monta `/static` e as telas do servidor (3.11); um endereço desconhecido fora de `/api` mostra a página de erro.
2. **Autenticação** (`identity/deps.py`, `get_auth`): com `Authorization: Bearer`, vale o token de API (abaixo); sem ele, lê o cookie de sessão, confere o CSRF em métodos que alteram dados, **relê o usuário e os grupos a cada requisição** (mudanças de papel valem na hora) e monta o `Actor`. Com a senha provisória (`must_change_password`), só três rotas funcionam até a troca. O `Auth` leva `session` **ou** `token` (os services só usam `user` e `actor`); o que só faz sentido na interface (sair, trocar a senha) pede `require_session()`.
   - **Token de API** (`api_tokens`, docs/05): age em nome de um usuário, com as permissões e a visibilidade dele; sem cookie e sem CSRF. O escopo `read` só passa em `GET`; `write` também altera. Um token nunca passa por `require(P.X)`: administração, auditoria e clientes ficam fora do alcance dele, mesmo o de um administrador. No banco fica só o SHA-256; o valor (`tf_…`) aparece uma vez, na criação: pela tela `/meus-tokens` (rotas `/me/tokens`, só com sessão: um token não cria nem revoga tokens) ou pelo `chamados token create`. Criar e revogar ficam em `identity/tokens.py` (`issue_api_token`, `revoke_api_token`), com a auditoria. Quem tem `admin.users` vê os tokens ativos de todos e revoga qualquer um (`/admin/tokens`, rotas `/admin/api-tokens`); criar continua só com a própria pessoa. Usuário inativo ou excluído, token revogado ou vencido: 401. Desativar ou excluir a pessoa também revoga os tokens dela (`revoke_user_api_tokens`, com a auditoria): reativar a conta não traz de volta um token que pode ter vazado. Trocar a senha não revoga.
   - **`Idempotency-Key`** (`identity/idempotency.py`, um middleware ASGI, porque só ele vê a resposta inteira): num `POST` em `/api/` com `Authorization` e a chave, a primeira resposta de sucesso (2xx) fica em `idempotency_keys` e volta igual, com `Idempotent-Replayed: true`, para a mesma chave do mesmo token, sem executar de novo. Mesma chave com outro corpo: 422; a primeira ainda em andamento: 409 (parada há mais de 5 min, a nova assume); erro não fica guardado. Opcional; só age com um token válido (sem ele, a requisição segue e o app responde 401, então um token revogado não recebe a resposta guardada); pela interface (sessão) e nas rotas `/api/v1/auth/`, ignorada; o `Set-Cookie` nunca é guardado.
3. **Rota → service:** rotas simples (cadastros) fazem o trabalho no próprio `router.py`; quando há regra de negócio, a rota delega a um `service.py`. Não existe camada de *repository*: os services usam o SQLAlchemy diretamente. Nos chamados, a montagem das respostas de leitura (lista, detalhe, tarefas, histórico) fica em `queries.py`, sem objetos HTTP de resposta: a API, as telas e as integrações que vierem a usam igual.
4. **Transação:** cada operação faz um único `commit` no fim. Histórico (`ticket_events`) e auditoria (`audit_log`) entram na **mesma transação** da mudança.
5. **Erros:** qualquer `HTTPException(status, "mensagem em português")` vira Problem Details (`{"type", "title", "status", "detail"}`) em `core/errors.py`, com `title` e `detail` traduzidos para o idioma do `Accept-Language` (3.6). Erros de validação viram 422 com a lista `errors`; exceções não tratadas viram 500 e vão para o log. Os services também sinalizam a recusa de uma regra com `HTTPException` (o status já diz o tipo: 403, 404, 409, 412, 422); é o erro de domínio do projeto, de propósito, sem uma hierarquia própria de exceções. Quem chama um service sem HTTP traduz a mensagem: as telas com `Page.api_message()`, e um adaptador novo (ex.: um servidor MCP) faz o mesmo com `core.i18n.translate`.

### 3.2 Configuração (`config.py`)

Variáveis de ambiente (em produção, `/etc/ticketflow/env`; em desenvolvimento, `backend/.env`):

| Variável | Padrão | Uso |
|----------|--------|-----|
| `DATABASE_URL` | `postgresql+psycopg://chamados:chamados@localhost:5432/chamados` | Banco |
| `LOG_LEVEL`, `LOG_FORMAT` | `INFO`, `json` | Logs (`console` em desenvolvimento) |
| `APP_BASE_URL` | `http://localhost:8000` | Endereço usado nos links dos e-mails |
| `COOKIE_SECURE` | `true` | Cookie só em HTTPS (desligar sem HTTPS) |
| `SESSION_IDLE_HOURS`, `SESSION_MAX_DAYS` | `8`, `7` | Expiração das sessões |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_STARTTLS`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | sem `SMTP_HOST` | Sem SMTP, os e-mails vão para o log |
| `FILES_DIR` | `/var/lib/ticketflow/files` | Anexos (só o usuário do serviço acessa; o backup, fora do programa, copia junto com o banco) |

### 3.3 Módulos

| Módulo | Arquivos | Responsabilidade | Rotas |
|--------|----------|------------------|-------|
| `identity` | `models` (User, UserSession, AuthToken, ApiToken, IdempotencyKey), `router` (login, `/me`), `admin_router` (usuários), `admin_tokens` (tokens de todos), `deps`, `sessions`, `passwords`, `tokens` (segredos e tokens de API), `idempotency` (middleware da `Idempotency-Key`), `ratelimit`, `service` (convites e e-mails), `schemas` | Login, sessões e CSRF, senhas (Argon2id), convite e redefinição, força bruta, usuários, idioma da pessoa | `/auth/*`, `/me` (com `/me/tokens`), `/users`, `/admin/api-tokens` |
| `organization` | `models` (Role, Team, TeamMember), `router` | Papéis, grupos e membros | `/teams` |
| `catalog` | `models` (Category, TicketStatus, ResolutionCode), `router` | Árvore de categorias (até 3 níveis; sem tela desde que saíram dos chamados), status por `kind`, códigos de resolução | `/categories`, `/statuses`, `/resolution-codes` |
| `clients` | `models` (Client), `router`, `documents` (CPF, CNPJ alfanumérico, telefone, CEP) | Cadastro de clientes pessoa física e jurídica, com contato e endereço; sem exclusão (inativa) | `/clients` |
| `tickets` | `models`, `schemas`, `router`, `service`, `queries` (leituras montadas nos schemas de saída), `rules`, `visibility` | Chamados, comentários, observadores, atribuição (um ou mais responsáveis), transferência, transições e histórico | `/tickets/*` |
| `system` | `models` (SystemSetting, WorkSchedule), `router`, `service`, `work_hours` (expediente e vigências) | Configurações da instalação: idioma padrão, cores, logotipo, expediente; idioma efetivo de um usuário | `/branding`, `/admin/settings`, `/work-hours` |
| `audit` | `models` (AuditLog), `service` (`record()`), `router` | Auditoria de login e administração | `/admin/audit-log` |
| `attachments` | `models` (Attachment), `router`, `service` (vínculo, lista, limpeza), `files` (tipos aceitos, limites, nome saneado), `storage` (disco) | Anexos dos chamados: envio em duas etapas, download com a permissão do chamado | `/uploads`, `/attachments/{id}` |
| `reports` | `models` (ReportModel), `schemas`, `service` (escopo, dados do período, horas fora do expediente), `builder` (construtor guiado e modelos prontos), `saved` (modelos da pessoa), `pdf` (ReportLab), `model_pdf` (PDF de um modelo e o do cliente), `csv_export`, `router` | Relatórios de horas: por pessoa, cliente e dia, horas extras, PDF e CSV; modelos pessoais com blocos do construtor (3.7.2) | `/reports`, `/reports/options`, `/reports/pdf`, `/reports/csv` |
| `notifications` | `email` (`Mailer`), `handlers` (quem recebe o quê), `messages` (textos), `tasks` (envio pelo worker) | E-mail por SMTP ou para o log; notificações dos chamados (3.13) | — |
| `mcp_server` | `server` (ferramentas, `running()` no lifespan, rota `Endpoint`) | Servidor MCP para assistentes de IA, com o token de API da pessoa (3.14) | `/mcp` (fora de `/api`) |
| `jobs` | `models` (OutboxEvent, Job), `service` (outbox, fila, repasse, agenda, limpeza), `worker` (loop, tarefas, rotinas, handlers) | Outbox de eventos, fila de tarefas e o processo `chamados worker` (3.12) | — |

Os módulos podem importar modelos e services uns dos outros (por exemplo, `tickets` usa `catalog`, `organization` e `identity`), mas **a decisão de permissão de um chamado só acontece em `tickets`** e **o registro na auditoria só por `audit.service.record()`**.

A lista completa de rotas, com os schemas, está em `/api/docs` (Swagger) e sai em JSON por `chamados openapi`. As convenções da API (paginação por cursor, `public_id`, Problem Details) estão em [docs/05](docs/05-api.md).

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
- **As permissões em vigor vêm do código** (`ROLES` em `core/permissions.py`, pelo código do papel do usuário). A tabela `roles` também guarda a lista de cada papel (cópia gravada pela migração 0002, mais as permissões acrescentadas depois em `NEW_PERMISSIONS` das migrações, como a 0010 e a 0015, menos as retiradas em `REMOVED_PERMISSIONS`, como a 0016; um teste confere), mas ainda não é lida: ela prepara os papéis personalizados de depois da v1.0.

### 3.5 Chamados (`modules/tickets/`)

- **Identificação:** `id` interno (bigint), `public_id` (UUID, exposto) e `number` (sequência `ticket_number_seq`, começa em 1000). As rotas aceitam o número ou o UUID (`/tickets/1234`).
- **Status:** a tabela `ticket_statuses` tem um `kind` fixo (`open`, `waiting`, `delivered`, `closed`, `canceled`, `approval`); `delivered` é o Entregue, a revisão do supervisor. As regras usam só o `kind`, e cada mudança vai para o status padrão do `kind` de destino.
- **Transições:** `rules.TRANSITIONS` define, para cada ação (`wait`, `resume`, `close`, `reopen`, `cancel`), de quais `kind` se sai, para qual se vai, quem pode e se exige comentário ou código de resolução. O comentário da transição é gravado como comentário do chamado; o de conclusão leva `is_solution`.
- **Sem prioridade:** chamados não têm prioridade, impacto nem urgência (removidos na migração 0016). Eventos antigos com essas mudanças continuam no histórico.
- **Status personalizados:** o admin cria (nome + `kind`: open, waiting, delivered, closed, canceled), renomeia, ordena (`PUT /statuses/order`) e remove em Configurações (`admin.settings`). O `kind` não muda depois de criado. Cada `kind` precisa de ao menos um status; ao remover, os chamados vão para o padrão do mesmo `kind`, e se o removido era o padrão o próximo da lista assume. O primeiro status criado de um `kind` vira o padrão. Ações em `audit_log` (`ticket_status.*`).
- **Status no formulário:** além das transições do fluxo, a ação `set_status` (quem tem `ticket.transition` no grupo) escolhe qualquer status no registro (`status_id`, padrão Pendente) e na edição, sem comentário nem código de resolução. `_apply_status` acerta `closed_at` e `canceled_at` e conta a reabertura ao sair de um `closed`. Com `finished_at` (só junto de um `status_id` concluído ou cancelado, diferente do atual; nem no futuro nem antes do `started_at`), essa é a data gravada, e ela vai no evento; o quadro a usa no mês passado. O evento é `ticket.status_changed` sem `action`. Para um status `closed`, a ação também exige `set_status_closed`, que só o supervisor do grupo e o admin têm (o agente entrega, e o supervisor conclui); no registro, um `status_id` `closed` também exige ser supervisor do grupo ou admin.
- **Categoria:** opcional e fora dos formulários do chamado (continua na API e no cadastro). Sem categoria, o grupo é obrigatório e o tipo é `incident`; `category_id: null` no PATCH tira a categoria.
- **Início:** `started_at` é quando o trabalho começou. Sem valor no registro, vale a hora do registro; a pessoa pode informar outra (nunca no futuro, com 5 minutos de folga para o relógio) e alterar depois, com evento no histórico. Na interface, o campo de data e hora acompanha a hora atual até ser mudado.
- **Cliente e contato:** para quem é o trabalho. `client_id` é **obrigatório** no registro e só aceita cliente ativo (um cliente inativado depois continua nos chamados antigos); no PATCH troca, mas `null` é recusado (422). A obrigação fica só na API: o banco aceita chamados antigos sem cliente (os relatórios os agrupam como "sem cliente"). O **contato** (quem pediu) é texto livre e fica em `beneficiary_name`, a antiga "pessoa atendida". Na interface, o campo de cliente (`client_picker` em `web/templates/_fields.html`) busca em `/clientes/opcoes`, que chama `GET /clients/options` (qualquer pessoa logada; só clientes ativos, só o id e o nome, busca pelo nome ou nome fantasia). Os setores atendidos (`departments`, `tickets.department_id`) saíram do sistema na migração `0034`.
- **Histórico:** fica só no banco e em `GET /tickets/{id}/events`; a linha do tempo da tela mostra só o registro e os comentários (decisão do usuário, 2026-10-13). Cada mudança chama `service.add_event()`, que grava em `ticket_events` com `payload` (antes/depois, com id **e nome** das referências na data do evento) e, na mesma transação, no `outbox` (3.12). Feita fora da interface, a mudança leva `via` no payload (`"api"`, por um token de API; `Auth.via`); pela interface, não há `via`. A tabela **só aceita inserção**: uma trigger da migração 0004 recusa `UPDATE` e `DELETE`. O comentário novo não vai para o histórico, mas vai para o outbox (`comment.created`, gravado por `_comment()`).
- **Responsável obrigatório:** todo chamado tem responsável (`tickets.assignee_id` NOT NULL desde a migração 0028); não há fila de não atribuídos nem "devolver à fila". O registro exige `assignee` (`"me"` ou um membro ativo do grupo); é nos próprios grupos, e quem tem `ticket.view_all` (admin) registra em qualquer grupo ativo, mas só fica como responsável se for membro dele; `POST /assign` só troca de responsável, e a transferência exige `assignee_id`, um membro ativo do grupo de destino.
- **Quem sai não leva chamados abertos:** excluir ou desativar um usuário (todos os grupos) e tirá-lo de um grupo (só os chamados daquele grupo) chamam `service.release()` na mesma transação: nos chamados abertos (`open`/`waiting`/`delivered`), quem era um dos responsáveis sai da lista; no lugar do principal fica o próximo da lista ou, sem ninguém, um supervisor ativo do grupo (o primeiro em ordem alfabética), que recebe o e-mail de atribuição. O evento é `ticket.assignees_changed`, com quem fez a ação de administração. Sem supervisor, o chamado continua com a pessoa, e a tela de administração mostra os números (`service.still_assigned`).
- **Mais de um responsável:** `tickets.assignee_id` é o responsável principal e `ticket_co_assignees` guarda os demais (no registro, `co_assignee_ids`; depois, `PUT /assignees` com a lista inteira, por quem tem `assign_others`; quem entra é sempre membro ativo do grupo). No `PUT`, quem já era responsável e saiu do grupo pode ficar ou sair, o principal continua se estiver na lista, senão o primeiro assume; o evento é `ticket.assignees_changed` (`added`, `removed` e, se o principal mudou, `assignee`). Para regras, visibilidade (regra 3), fila Meus, aviso de novidade e o filtro por responsável, todos contam igual (`visibility.assigned_to`). Transferir tira os demais; trocar o principal os mantém. A interface envia quem registra como principal, se estiver na lista, senão a primeira pessoa; na lateral do chamado, "Atribuir a" acrescenta uma pessoa ou o grupo todo, e cada responsável tem um botão para sair (menos o último).
- **Grupos que atuaram:** `ticket_teams` recebe o grupo na criação e a cada transferência; alimenta a regra 2 da visibilidade.
- **Tarefas (comentários):** o autor edita (texto, tempo, `done_at`) e remove (`DELETE`, só marca `deleted_at`; evento `comment.deleted` com o texto e o tempo) a qualquer momento. Toda leitura de comentários (lista, tempo gasto, busca, novidades, anexos do detalhe) ignora os removidos; a lista ordena por `done_at`.
- **Tempo gasto:** cada comentário (andamento) pode ter `time_spent_minutes` (opcional, 1 a 60 000), no comentar, na mudança de status (vai no comentário da transição; sem comentário, 422) e na edição (o valor anterior vai em `before_time_spent_minutes` do `comment.edited`). O detalhe traz `time_spent_minutes` (total) e `time_by_person` (soma por autor, `service.time_by_person`), mostrados na lateral.
- **Observadores e menções:** `ticket_watchers` (`kind` = `watcher` ou `mentioned`). As menções chegam em `mention_ids` (no registro, no comentário e no comentário de uma transição, como retomar e reabrir): o texto guarda só "@Nome".
- **Lista:** ordenação padrão (mais antigo primeiro) com paginação por cursor (base64 de data e id). Filtros: `team`, `assignee` (`me` ou o id), `status` (kinds) e `q`.
- **Total de horas na lista:** cada item traz `time_spent_minutes` (`service.time_spent()`, subconsulta da soma das tarefas não removidas).
- **Status em massa:** `POST /tickets/bulk/status` (`numbers`, `status_id`; até 200). Cada chamado passa por `load` (visibilidade), pela ação `bulk` (`ticket.bulk`: supervisor do grupo ou admin) e por `_change_status` (as mesmas regras do `set_status`, inclusive a revisão). Os que falham voltam em `failed`, com o motivo traduzido; os demais mudam numa transação só.
- **Filas:** o parâmetro `view` da lista (`service.view_filter`): `mine` (sou o responsável, `open`/`waiting`/`delivered`), `waiting` (meus grupos, `waiting`/`delivered`), `watching` (sou observador, `open`/`waiting`/`delivered`) e `all` (tudo o que vejo). `GET /tickets/counts` conta as três primeiras numa consulta só.
- **Novidade:** comentário de outra pessoa depois da minha última visita (`has_news` em cada item da lista, mostrado como ícone ao lado do título; a aba Com novidades saiu em 2026-10-15). A visita fica em `ticket_reads` e é gravada pelo `GET /tickets/{id}` (`service.mark_read`). A reabertura exige comentário, por isso também vira novidade.
- **Busca (`q`):** `search_vector` (colunas geradas, índice GIN) em `tickets` (título peso A, descrição peso B) e em `ticket_comments`, na configuração `pt_br` (português sem acentos). Cada palavra vira prefixo (`impress:*`) e todas precisam aparecer. Também acha pelo número (`1234` ou `#1234`), pelo nome do cliente e pelo contato (`unaccent` + `ILIKE`). Passa pelo filtro de visibilidade como qualquer leitura.
- **`ETag` (concorrência):** `service.etag()` é um hash dos campos que o `PATCH` altera (`EDIT_FIELDS` + `status_id`): tarefas, responsáveis e observadores não o mudam. Sai no header `ETag` do `GET /tickets/{id}` e do `PATCH`, e no campo `etag` do detalhe. O `PATCH` com `If-Match` relê esses campos com a linha travada (`FOR UPDATE`) e responde **412** se mudaram; sem `If-Match`, grava como antes (opcional, para não quebrar integrações). `If-Match: *` passa.
- **Quem mais está vendo:** `presence.touch()`, na tabela `ticket_presence` (UNLOGGED: dado passageiro): quem abriu ou perguntou nos últimos 45 s. No banco, e não na memória, porque a API roda com vários workers (seção 8); as linhas vencidas saem a cada pergunta. Tarefas novas desde a última que a tela mostrava: `service.comments_since()` (de outras pessoas, não removidas).

### 3.5.1 Anexos (`modules/attachments/`)

- **Duas etapas** ([docs/11 §11.4](docs/11-anexos-e-arquivos.md#114-fluxo-de-envio-em-duas-etapas)): `POST /uploads` (multipart, campo `file`) guarda o arquivo sem dono e devolve o id; o registro, o comentário, a mudança de status e a edição (da descrição ou de um comentário) recebem `attachment_ids` e chamam `attachments.service.link()`. Só quem enviou vincula, e uma vez só; o que já está no mesmo lugar é ignorado (a edição manda de novo as imagens que o texto já tinha).
- **Enviar** exige `ticket.comment` ou `ticket.create`; o vínculo passa pelo `allowed_actions` da ação (comentar, editar…). **Baixar** (`GET /attachments/{id}`) passa por `tickets.service.load`, ou seja, pela visibilidade do chamado; um envio ainda sem dono só quem enviou baixa. Download de chamado confidencial vai para a auditoria.
- **Tipos** (`files.py`): lista fechada de extensões, conferidas pelos primeiros bytes (PNG, JPEG, PDF, ZIP dos formatos Office/ODF…; os de texto não podem ter byte nulo). O `content_type` gravado vem da extensão conferida, nunca do navegador. Zip, 7z, Office com macro, executáveis, html e svg são recusados.
- **Limites:** 25 MB por arquivo (413), 10 por envio, 200 MB por chamado.
- **Disco** (`storage.py`): `FILES_DIR/attachments/AAAA/MM/<uuid>`, gravado num temporário e renomeado; o nome original (saneado) e o SHA-256 ficam só no banco.
- **Download:** `inline` para imagens e PDF, `attachment` para o resto, com `X-Content-Type-Options: nosniff` e `Content-Security-Policy: sandbox`.
- **Limpeza:** a rotina diária `attachments.purge` do worker (3.12) apaga os envios sem dono há mais de 24 h; `chamados attachments purge` faz o mesmo à mão.
- O detalhe do chamado traz `attachments` (do registro e de todos os comentários, com `comment_id`); a interface mostra cada anexo no seu comentário e todos na lateral.

### 3.6 Idiomas (backend)

- Idiomas: `pt-BR` (padrão) e `en` (`core/i18n.py`).
- **Mensagens:** são escritas em português no código. `core/errors.py` traduz `title` e `detail` pelo catálogo `EN` quando o `Accept-Language` pede inglês; nas telas, `Page.api_message()` traduz pelo idioma da pessoa. Um teste percorre o código (AST) e falha se alguma mensagem de `HTTPException` não estiver no catálogo.
- **E-mails:** textos em `identity/service.EMAILS` (convite, redefinição, bloqueio) e em `notifications/messages.TEXTS` (chamados), por idioma. O idioma é o de quem recebe: `users.locale` ou o padrão do sistema (`system.service.user_locale`).

### 3.7 Configurações (`modules/system/`)

- Tabela `settings` com chave e valor (jsonb). Sem a linha, vale o padrão. Chaves: `locale`, `colors` (`brand`, `neutral`, `background`), `logo` (imagem em base64, tipo e sha256) e `work_hours` (desde a 0040, só os feriados: `holidays`, que valem para todos).
- **Expediente** (`work_hours.py`, docs/14 §14.7): dias (`weekdays`, 0 = segunda), início e fim, em vigências (`work_schedules`, a partir de `valid_from`; nulo, desde sempre) da instalação, de um grupo ou de uma pessoa; sem dias e horário, a vigência devolve a pessoa ou o grupo ao de cima. Precedência num dia: o da pessoa > o do grupo (de quem está em **um só** grupo ativo com expediente, pela participação atual: não há histórico de participação) > o da instalação (padrão seg–sex 08:00–18:00). `Calendar` (lido por `load_calendar`, uma vez por requisição: as vigências e as participações nos grupos que têm alguma) responde o expediente de (pessoa, dia) (`source`: de onde vem, e `conflict`, os grupos de quem está em dois ou mais) e a janela do dia em UTC (`window`, em cache). Gravar uma vigência (`save_vigency`) substitui a da mesma data, e uma igual à anterior não fica gravada; `set_schedule` grava a de um grupo ou de uma pessoa com a auditoria (`team.work_hours_set`/`user.work_hours_set`, antes e depois). `GET /work-hours` (todos) responde o da instalação de hoje, com os feriados; `PUT /admin/settings/work-hours` grava uma vigência da instalação a partir de `valid_from` (sem ele, hoje) e os feriados (`settings.updated`).
- `GET /branding` é **público**: a tela de login também usa as cores, o logotipo e o idioma.
- O logotipo é servido por `GET /branding/logo?v=<hash>`, com cache permanente (o endereço muda quando a imagem muda). Só PNG, JPEG e WebP, conferidos pelos primeiros bytes; SVG é recusado porque pode conter scripts.
- O backend guarda só as **três cores**; a paleta inteira é derivada em `web/palette.py` (4.2).

### 3.7.1 Clientes (`modules/clients/`)

- Pessoa física (`person`: CPF, RG, nascimento) ou jurídica (`company`: CNPJ, nome fantasia, inscrições estadual e municipal, pessoa de contato). Os campos do outro tipo ficam nulos.
- Obrigatórios: nome completo e CPF (PF) ou razão social, nome fantasia e CNPJ (PJ), mais CEP, cidade e UF (a API confere; o banco aceita cadastros antigos sem eles). O CPF/CNPJ é validado e único (restrição no banco); o nome também não repete (a API compara sem maiúsculas, acentos e espaços a mais).
- Documentos, telefones e CEP são gravados sem pontuação; a interface formata (`web/formatting.py` na tela e `static/js/clientes.js` enquanto se digita). O CNPJ aceita o formato alfanumérico (julho de 2026): mesmo cálculo dos dígitos, com o valor de cada caractere = ASCII − 48.
- A validação fica no router (`_clean`), com mensagens do catálogo de idiomas. O formulário envia o cadastro inteiro (`PUT`).
- Permissões: `client.view` e `client.manage`, que nenhum papel tem: valem só para membros do grupo **Administradores** (ativo; nome comparado sem maiúsculas, `CLIENT_MANAGERS_TEAM` em `core/permissions.py`), mesmo com papel Administrador. Renomear o grupo tira a permissão de todos. Os demais só escolhem o cliente pelo nome (`GET /clients/options`). A auditoria registra só **quais campos** mudaram, sem os dados pessoais.
- Ligação com os chamados: `tickets.client_id` (3.5).

### 3.7.2 Relatórios (`modules/reports/`)

- Regras de negócio em [docs/14 §14.7](docs/14-relatorios-e-indicadores.md#147-relatórios-de-horas-pedido-do-usuário-2026-10-15) e §14.8 (relatórios personalizados, em fases). Calculado na hora, sem tabela própria: as somas (horas, tarefas, chamados por pessoa, cliente, grupo, status e dia) vêm do banco, e a hora extra, de cada tarefa em Python (`service.outside_minutes`), só nas que podem tê-la.
- **Filtros:** grupo, pessoa, cliente (mais `no_client`, os chamados sem cliente) e status aceitam vários valores (o parâmetro repetido); lista vazia é "todos" e, com valores, vale qualquer um (`service.Filters`).
- **Escopo:** `service.resolve` confere os filtros (cada grupo e cada pessoa precisa estar ao alcance, senão 403) e `_own_or_supervised` restringe as linhas: `report.view_all` vê tudo; os demais, o próprio trabalho mais os chamados dos grupos supervisionados. Sempre junto com `ticket_visibility_filter`.
- **Dados do período:** `service.facts(db, auth, f, want, known)` faz as consultas uma vez, só do que `want` (`service.Want`) pede: as **linhas** de cada parte (`service.Part`: todas as tarefas, para a lista e o CSV; as que podem ter hora extra; os chamados registrados, concluídos, cancelados e em aberto no fim, numa consulta só com as condições num `OR`, separados em Python pelas mesmas datas, com os responsáveis que a pessoa pode ver e, no em aberto, o status do fim, pela primeira `ticket.status_changed` depois dele; e o tempo líquido dos concluídos, `net_lead`, por `service.net_minutes` sobre as mudanças de status) e as **somas** de cada medida que soma (`service.Sums`: o total e a soma de cada chave por agrupamento, `service.Group`: pessoa, cliente, grupo, status, dia, hora do dia e dia da semana × hora, o `weekday_hour` do mapa de calor; a semana, o mês e o dia da semana saem do dia). Horas e tarefas são somadas no banco (`GROUPING SETS`, uma expressão fixa por agrupamento); a hora extra, em Python (`add_up`), sobre as tarefas que não cabem inteiras numa janela do expediente de quem as fez (`_may_have_overtime`: as janelas do mesmo `Calendar.window`, uma por dia do período, passadas ao SQL num vetor; com o expediente da instalação para todos, um par de vetores só, a consulta de antes; quem tem outras janelas no período, o próprio ou o do grupo, ganha o par dele, escolhido pelo autor num `CASE`, e as pessoas com as mesmas janelas dividem o par); registrados, concluídos e cancelados, no banco (`count(*) FILTER`, cada responsável conta e o total conta uma vez) ou das linhas, quando elas vieram; o em aberto, das linhas. Devolve `Facts` com os nomes (`UserName`, `ClientName`, `TeamName`: o id público e o nome, sem o objeto do ORM). Quem chama pede o que usa: a tela, o PDF do modelo, o CSV de um bloco e a prévia do editor, `builder.needs(blocos)` (no período anterior do "Comparar", só os blocos que comparam); a lista do detalhar, as linhas do conjunto da medida; o relatório para o cliente, as linhas das tarefas, dos registrados e dos concluídos; `service.build` (API, PDF e CSV das tabelas), as somas de `BUILD_SUMS`. O `builder.run` recusa (`ValueError`) uma parte ou uma soma que não veio, em vez de contar zero. `known` (`service.Lookups`: o expediente, `work_hours.Calendar` com as vigências e os feriados, e os status) vem lido uma vez por requisição: a tela o lê no `load_state` (`State.lookups`) e o passa às opções do filtro e a cada `facts`; sem ele, o `facts` lê.
- **Construtor e modelos (docs/14 §14.8):** `builder.ReportConfig` (versão, descrição, período relativo ou datas, filtros, formato das horas e até 12 blocos `Block`: visual × agrupar por × medidas) é o que `report_models.config` guarda; `builder.BUILTINS` são os modelos prontos (as abas Produtividade, Clientes e Horas extras); `builder.trend` dá a tendência de cada medida de um bloco de cartões (a sparkline, por dia ou por semana com a regra do `DAILY_LIMIT`; o `needs` pede, nos cartões, as somas por dia na mesma consulta, e o em aberto fica de fora); `builder.run` calcula um bloco a partir do `Facts`, das somas (as medidas que somam) ou das linhas (a mediana, a reabertura, a idade) (catálogo fechado: nada do que a pessoa escolhe vira SQL, só as expressões fixas de cada agrupamento; contagens e horas somam, os tempos até a conclusão são a mediana (ou a média, com `Block.aggregate`, e o nome "Média…") e a reabertura, a média em centésimos de ponto; as derivadas, `builder.DERIVED`, são uma conta entre duas somas, inclusive os chamados distintos com tarefa, `worked`, um `count(distinct)` no mesmo GROUPING SETS só quando pedido, que não soma de um dia para outro e tem os agrupamentos semana, mês e dia da semana próprios; as tarefas por dia útil dividem por `builder.workdays` (agrupadas por pessoa, os dias do expediente de cada uma; no resto, os da instalação); sem base, `None`); `builder.comparison_period` dá o período da comparação (`PeriodSpec.compare`: `none`, `previous`, pelo `previous_period`, ou `year`, pelo `year_before`), `builder.matching` acha a linha correspondente de antes (a tela e o CSV do bloco) e `builder.next_period` é o simétrico do `previous_period` (as setas da tela); `builder.upgrade` converte a configuração de uma versão antiga (`saved.config_of` a usa ao ler; versão 2: `compare` deixou de ser booleano); `builder.check_block` recusa as combinações sem sentido (422), e `builder.dimensions_for`/`measures_for` dão as que cabem em cada visual, as únicas que o editor oferece (um teste confere que os dois concordam); `builder.relative_period` resolve os períodos relativos. Ajustes por bloco: `Block.period` (`BlockPeriod`, um relativo; None é o da tela) e `Block.filters` (um `FilterSpec`; None é o da tela), que só restringe o da tela campo a campo (`builder.narrow`, que diz os campos sem nada em comum); `Block.width` (None, a regra do `reports_blocks.wide`; `half`/`full` valem mais que ela) e `Block.color` (um de `builder.SERIES`, só nos `builder.COLORED`; None é a `chart-1`); `Block.columns` (as colunas da lista de tarefas, de `builder.TASK_COLUMNS`, sempre nessa ordem; None: `DEFAULT_COLUMNS` na tela e no PDF e `CSV_COLUMNS` no CSV, as de antes); a ordem das medidas é a das colunas da tabela (o editor guarda a ordem em `b<i>-sequencia` e as setas são `acao=medida-subir-<bloco>-<medida>`); `Block.hide_others` (com o `top`, sem a linha "Outros": `Result.cut`, e o total da tabela e do CSV diz que é o do período inteiro); `Block.hours` e `Block.decimals` (o formato das horas sobre o do modelo e as casas fixas; `reports_blocks.formatter` recebe o bloco, e o `_step` dos eixos segue as casas); `Block.height` (`s`, `m`, `l`, só nos `builder.SIZED`: na tela, `h-28`/`h-40`/`h-56` e, no mapa, a altura das células; no PDF, `Chart.scale`/`Heatmap.scale`). `saved` cria, altera (nome único por pessoa, um só modelo inicial) e apaga os modelos da pessoa: o de outra pessoa responde 404. A ordem e as abas escondidas são uma preferência da pessoa (`report_preferences`, chave `user_id`: `saved.TabPrefs`, lida por `saved.tab_prefs` e gravada por `saved.save_tabs`, sempre com o `auth.user.id`); `saved.arrange` aplica a preferência à ordem de sempre (um id que não existe mais sai, um modelo novo entra no fim, o inicial sempre aparece). Os modelos só têm tela, sem rota de API.
- **Hora extra:** `service.outside_minutes(done_at, minutos, calendário, pessoa)`: a tarefa termina em `done_at`; conta o que fica fora da janela do expediente da pessoa em cada dia que a tarefa atravessa (no fuso da máquina; a da meia-noite em diante usa a do dia seguinte), nos dias que não são de trabalho e nos feriados. O `Report.work_hours` da API continua sendo um expediente só: o da instalação no último dia do período, com os feriados.
- **PDF da API:** `model_pdf.render_hours` (ReportLab, fontes padrão do PDF, sem pacotes do sistema), no idioma do parâmetro `locale` ou, sem ele, no do `Accept-Language`, gerado numa thread; um modelo fixo montado do `service.build` (o "Expediente" do cabeçalho pelo `service.describe_use`, como na tela; os totais em `Cards`, por pessoa, por cliente e as tarefas fora do expediente em `Grid`, as `HOURS_LISTED` primeiras com a nota) e desenhado pelo `render_model`, com os textos de `model_pdf.HOURS_TEXTS` (os módulos não dependem dos catálogos de web/); cada download vai para o `audit_log` (`report.exported`, com `format`).
- **Relatório para o cliente:** `ReportConfig.client` (`builder.ClientSpec`: a abertura e as observações, livres; as colunas, de `builder.CLIENT_COLUMNS`, sempre nessa ordem; `show_hours`, a coluna e o total das horas) e `ReportConfig.show_people`. A lista fechada não tem nada de organização interna (docs/14 §14.8.5).
- **PDF de um modelo e do cliente:** `model_pdf` só desenha: recebe os blocos já formatados (`Cards`, `Chart`, `Grid`) ou os totais e os chamados do cliente (`service.client_tickets`), com os textos traduzidos pela tela, e a página (`model_pdf.Page`: A4 em pé ou deitado, a largura útil que cada desenho recebe, e o rodapé de cada página, desenhado no fim por um `canvasmaker`, `_numbered`, que guarda as páginas para saber o total do "Página n de total"). As colunas da tabela têm a largura do texto mais longo (`_widths`) e só a célula que não cabe numa linha vira `Paragraph` (`_cell`): um por célula levava segundos numa tabela longa. No modelo, `ReportConfig.pdf` (`builder.PdfSpec`: orientação, título, rodapé) e `Block.in_pdf` (o `/relatorios/pdf` nem calcula os blocos de fora). Gráficos em vetor (`reportlab.graphics`), com as cores de série do modo claro da paleta da instalação (`model_pdf.Series`: `chart-1` ou a cor do bloco, `Chart.color`, pelo nome do token; `chart-2` nas horas extras das empilhadas e `chart-before` na série do período anterior, `Chart.before`; o Δ da tabela vira "Var.", que as fontes padrão têm); o sinal de menos (U+2212) vira hífen, porque as fontes padrão do PDF não o têm. O logotipo vem das Configurações (o Pillow lê PNG, JPEG e WebP).
- **CSV:** `csv_export.render`, uma tabela da tela (`table`: `people`, `clients`, `overtime`) ou todas as tarefas (`tasks`, que pede `build(..., all_tasks=True)`; `Report.tasks` fica fora da resposta da API). UTF-8 com BOM; em português, `;` e vírgula decimal; tempo em horas decimais e em minutos; texto livre que começa como fórmula (`=`, `+`, `-`, `@`) ganha um apóstrofo. As listas de tarefas (a da API e a do bloco) terminam com a coluna "Expediente": o de quem fez a tarefa no dia dela ("seg–sex 08:00–18:00"; na API, do `TaskRow.schedule`, fora do JSON). Mesma auditoria do PDF, com a `table`.

### 3.8 Auditoria × histórico

| | `audit_log` | `ticket_events` |
|--|-------------|-----------------|
| O quê | Login, falhas de login, bloqueios, administração (usuários, grupos, categorias, configurações), acesso a confidencial | Tudo o que acontece **em um chamado** |
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
| `0013` | `attachments` |
| `0014` | Grupo padrão "Administradores", com o `admin` como membro |
| `0015` | `ticket_co_assignees` (outros responsáveis) e `ticket.assign_others` para o agente |
| `0016` | Sem prioridade: saem `priority`, `priority_overridden`, `impact`, `urgency` e `ticket.set_priority` |
| `0017` | `ticket_comments.time_spent_minutes` (tempo gasto em cada andamento) |
| `0018` | `ticket_comments.done_at` (quando a tarefa foi feita) e `deleted_at` (tarefa removida) |
| `0019` | `ticket_statuses.is_review` e o status "Em espera de revisão" (`waiting`) |
| `0020` | "Entregue" passa a ser a revisão: sai o "Entregue" de conclusão (chamados vão para "Concluído") e o de revisão é renomeado |
| `0021` | Comportamento `delivered` (Entregue), com o status de revisão como padrão dele; sai `is_review` |
| `0022` | `users.deleted_at` (exclusão de usuário: a linha fica para o histórico, sem e-mail nem login) |
| `0023` | Clientes: telefones e e-mails viram listas (`phones`, `emails`); nome, CPF/CNPJ e endereço (menos CEP, cidade e UF) passam a opcionais no banco |
| `0024` | `users.display_name`: o nome que aparece no sistema (o completo fica no cadastro) |
| `0025` | Sai a restrição única de `clients.document`: o mesmo CPF/CNPJ pode estar em mais de um cadastro |
| `0026` | Volta a restrição única de `clients.document` (desfaz a `0025`) |
| `0027` | `client.manage` sai dos papéis (passa a vir do grupo Administradores) |
| `0028` | `tickets.assignee_id` NOT NULL: todo chamado tem responsável |
| `0029` | `client.view` também sai dos papéis: o cadastro de clientes é só do grupo Administradores |
| `0030` | `outbox` (eventos de domínio) e `jobs` (fila de tarefas), consumidos pelo worker |
| `0031` | Índice `ticket_comments_done_idx` (`done_at` das tarefas não removidas), para o período dos relatórios |
| `0032` | `api_tokens` (tokens de API, em nome de um usuário) |
| `0033` | `idempotency_keys` (respostas guardadas da `Idempotency-Key`) |
| `0034` | Sem setores atendidos: saem `departments` e `tickets.department_id` |
| `0035` | `tickets.canceled_at` (data do cancelamento; os já cancelados ficam com o `updated_at`) |
| `0036` | `report_models` (modelos de relatório pessoais: a configuração em JSONB, nome único por pessoa sem diferenciar maiúsculas, no máximo um inicial) |
| `0037` | Índice `tickets_created_idx` (`created_at`, `id`): a ordem da lista de chamados e do cursor |
| `0038` | `ticket_presence` e `login_ip_failures` (UNLOGGED): a presença no chamado e o limite de login por IP saem da memória, para valerem com vários workers |
| `0039` | `report_preferences` (a ordem e as abas escondidas de Relatórios, uma linha por pessoa, em JSONB) |
| `0040` | `work_schedules` (vigências do expediente da instalação, de um grupo ou de uma pessoa; única por dono e data, com `NULLS NOT DISTINCT`); o expediente da chave `work_hours` vira a vigência da instalação desde sempre, e a chave fica com os feriados (o downgrade devolve o da instalação de hoje à chave) |

- **Convenções:** `bigint GENERATED ALWAYS AS IDENTITY` + `public_id uuid` nas entidades expostas; `timestamptz` sempre; nomes de constraint previsíveis (`db/base.py`); nada é apagado nos cadastros (só desativado: `is_active`).
- **Compatibilidade:** só recursos do PostgreSQL **16 e 17** (`check.sh --completo` testa nos dois).
- **Sem JIT:** a engine do app (`db/engine.py`) conecta com `jit=off`. O filtro de visibilidade (vários `OR EXISTS`) infla o custo estimado, e o JIT levava ~0,7 s para compilar consultas que rodam em ~30 ms (medido pelo benchmark, 7.1). A configuração do servidor não muda; o motivo e as alternativas estão no [ADR 0012](docs/adr/0012-postgresql-sem-jit.md).
- **Nova migração:** gerar com o autogenerate do Alembic a partir dos modelos, **revisar à mão** (sequences, triggers, cargas iniciais e índices parciais não são detectados) e conferir que o `downgrade` funciona. O teste `test_migrations` desce até a base e sobe de novo.

### 3.10 Comando `chamados` (`cli.py`)

| Comando | Faz |
|---------|-----|
| `chamados db upgrade [rev]` / `downgrade rev` / `current` | Migrações |
| `chamados admin create --email … --name …` | Cria um administrador e mostra o link para definir a senha (recuperação de acesso) |
| `chamados token create --user … --name … [--read-only] [--days 365]` / `list` / `revoke id` | Tokens de API: cria (mostra o valor uma vez), lista os ativos e revoga; criar e revogar vão para a auditoria (`api_token.*`) |
| `chamados attachments purge` | Apaga os envios não vinculados há mais de 24 h, à mão (o worker já faz isso todo dia) |
| `chamados worker` | O worker (3.12): fica no ar até receber SIGTERM ou Ctrl+C |
| `chamados openapi [-o arquivo]` | Exporta o contrato OpenAPI, para integrações (5) |

### 3.11 Telas do servidor (`web/`, ADR 0011)

```
web/
├── __init__.py          router das telas (fora do OpenAPI), incluído em main.py
├── page.py              Page (sessão opcional, idioma, marca, can(), render), LoggedPage (exige
│                        login), Redirect, safe_next(), check_csrf(), flash()
├── auth.py              login, sair, esqueci a senha, convite, redefinição, troca obrigatória, idioma
├── tickets.py           / (vai para a lista), lista de chamados com as filas, status em massa
├── board.py             quadro (kanban): uma coluna por status; arrastar o cartão muda o status
├── ticket.py            registro, detalhe, ações da lateral, tarefas e a busca de clientes
├── clients.py           cadastro de clientes (lista e formulário)
├── admin.py             usuários e grupos (e membros), com o painel lateral
├── settings.py          Configurações: idioma, cores (prévia pelo HTMX), logotipo, status, expediente
├── work_hours.py        expediente nas telas: vigências em texto, o que vale hoje, o formulário
├── reports.py           relatórios: a tela (abas dos modelos, filtros, blocos, menu Baixar)
├── reports_state.py     relatórios: o que vem da URL (Params: modelo, período, filtros) e o estado
├── reports_blocks.py    relatórios: cada bloco formatado para a tela e o PDF; prévia do cliente
├── reports_downloads.py relatórios: PDF do modelo ou do cliente, CSV de um bloco, lista de chamados
├── reports_editor.py    relatórios: editor de modelos e Salvar filtros
├── tokens.py            meus tokens de API: criar (o valor aparece só na resposta), listar, revogar
├── admin_tokens.py      tokens de API de todas as pessoas (admin.users): filtro por pessoa, revogar
├── formatting.py        datas, "há 3 dias", duração, tamanho e os campos de data e hora (fuso da máquina)
├── markdown.py          render_markdown(): markdown-it-py com as regras do antigo markdown.ts
├── i18n.py              translate(): os catálogos de web/locales/ (4.3)
├── palette.py           paleta derivada das 3 cores (port do tema/paleta.ts; a borda escura subiu um tom)
├── templating.py        ambiente Jinja2, static() (endereço com a data do arquivo) e CachedStaticFiles
├── locales/             pt-BR.json e en.json, com as mesmas chaves (4.3)
├── templates/           base.html, card.html (cartão sem menu), app.html (menu e cabeçalho),
│                        _ui.html (macros), _fields.html (campos das telas de chamado), clients/, admin/,
│                        _icons.html, auth/, tickets/, board/, reports/ (index.html, editor.html, tickets.html, _blocks.html: os blocos da tela e da prévia, e _charts.html: gráficos em SVG)
└── static/              css/input.css (→ app.css gerado), js/ (tema.js, app.js, chamado.js, clientes.js,
                         configuracoes.js, quadro.js, vendor/htmx, vendor/tiptap), fonts/
```

- **Sem regra na tela:** a rota da tela chama a função da rota da API (`identity.router.login(...)`), o service ou, nos chamados, `tickets/queries.py`, e só monta o HTML. Se a função da rota pede `Response` ou `Request` só para cabeçalhos, a tela chama o service, sem objeto vazio. Os erros da API (`HTTPException`) viram a mensagem na tela, traduzida por `Page.api_message()`.
- **Sessão:** `get_page` lê o cookie `tf_sessao` (`load_session` + `session_auth`, as mesmas peças do `get_auth` da API). `LoggedPageDep` exige login (sem sessão, `/login?volta=…`) e, com a senha provisória, só abre `/trocar-senha` e `/sair`.
- **Permissão das telas de administração:** as rotas de administração da API conferem a permissão numa dependência (`require(P.X)`), que **não roda** quando a tela chama a função direto. Por isso a tela usa `requires(P.X)` (`page.py`), que confere a mesma permissão antes; as ações de chamado não precisam, porque a regra fica no service (`allowed_actions`). O `tests/telas/test_web_permissoes.py` garante isso: acha as funções da API protegidas por `require`, as telas que as usam (direto ou por outra função do módulo; dentro de `if page.can("x")` a permissão x já conta) e falha se a tela não tiver o `requires` correspondente, ou se uma tela em `/admin/` não exigir a permissão da área (`AREAS`). Módulo novo de telas ou de API entra nas listas do teste.
- **Idioma:** o da pessoa ou o padrão do sistema; nas telas sem login, o padrão. `t("chave", nome=…)` nos templates. O catálogo é lido de novo quando o JSON muda (o `--reload` do uvicorn só olha os `.py`).
- **Atualização:** os templates, os catálogos e o `app.css` novos valem assim que o `deploy.sh` termina; o código Python, só depois do `systemctl restart`. Reinicie logo depois do deploy.
- **CSRF:** formulário que altera dados manda `csrf_token` (o valor do cookie `tf_csrf`) num campo escondido, conferido por `check_csrf()` com o hash da sessão. O login não precisa (ainda não há sessão).
- **Avisos:** `page.flash(response, ("success", texto))` antes de redirecionar; a próxima tela os mostra no canto (`toasts()` do `app.html`) e apaga o cookie `tf_aviso`. Os de sucesso somem em 5 s, contados de novo depois que o mouse e o foco saem deles.
- **Botões por permissão:** `page.can("ticket.create")` só mostra ou esconde (menu lateral, Novo chamado, seleção em massa); quem decide é a rota.
- **JavaScript (`static/js/app.js`):** comportamento por atributos `data-*`, sem build: menus em `<details data-menu>`, `<dialog>` (`data-abre-dialogo`), formulário que aplica ao mudar (`data-envia-ao-mudar`), avisos, a seleção do status em massa e a trava do envio duplo (um formulário POST já enviado não sai de novo até a resposta, ou por 5 s se ela não vier; `data-travado` no formulário e `aria-disabled` nos botões de envio, inclusive os de fora com `form="id"`). Também abre o calendário dos campos de data e a lista de horários dos campos de hora e do tempo gasto (`data-sugestoes`, que tira o `<datalist>` do navegador): os campos continuam os nativos (digitar e o valor enviado não mudam), mas a janela é um popover nosso, centralizado sob o campo, porque a do navegador não aceita CSS; na tela de toque fica a do sistema. Os `<select>` usam `appearance: base-select` (Chrome 135+) para a lista seguir o mesmo visual (`input.css`). O HTMX busca trechos (`hx-select` sobre a página inteira que a rota devolve, sem templates parciais), como o "Carregar mais" da lista.
- **Redirecionamento:** `raise Redirect(url)` em qualquer ponto (inclusive nas dependências) vira 303; num pedido do HTMX, vira `HX-Redirect` (a página inteira troca, ex.: login com a sessão expirada no "Carregar mais"). Sem sessão, só um GET guarda a página em `volta`; um POST volta para a tela inicial depois do login.
- **Erros:** fora de `/api`, `HTTPException` e erro de validação viram uma página (`web/errors.py`, `error.html`) em vez do JSON da API (ex.: o token CSRF de uma aba antiga). Os formulários sem sessão (login, senhas) recusam envio de outro site (`reject_cross_site`, pelo `Sec-Fetch-Site`). Endereços de volta passam por `safe_next()`, que só aceita caminhos deste site.
- **Cores:** `palette.stylesheet()` gera a folha das cores personalizadas, embutida no `<head>` (`<style id="tf-cores">`; a CSP aceita estilo embutido, não script). O tema claro/escuro fica no navegador (`tf-tema`, 4.2), aplicado pelo `tema.js` antes da primeira pintura.
- **CSS:** `scripts/css.sh` roda o Tailwind standalone (`pytailwindcss`, versão fixa no script) sobre `static/css/input.css` e procura classes só em `templates/` e `static/js/`. O `app.css` não vai para o git: o `deploy.sh` o gera, e em desenvolvimento o `ticketflow-css.service` (ou `scripts/css.sh --watch`) o gera de novo a cada mudança. **Cache:** o `/static` é servido por `CachedStaticFiles`: o endereço de `static()` (`?v=` com a data do arquivo em ns) fica um ano no navegador (`immutable`), sem nova pergunta a cada tela; por isso todo arquivo de `static/` citado num template passa por `static()`. As fontes, citadas pelo CSS sem versão, ficam no cache comum (ETag); a latina é pré-carregada no `base.html`.
- **Editor e Markdown:** descrição e tarefas são **Markdown** no banco. O `static/js/chamado.js` monta o Tiptap (empacotado num arquivo só em `static/js/vendor/`, gerado por `scripts/vendor-tiptap.sh`, que é o único passo com Node e só roda para trocar a versão) sobre o `<textarea>` do macro `editor()`, que continua levando o texto; sem JavaScript, fica o `<textarea>`. O `@` abre os colegas (JSON em `<script type="application/json" id="pessoas">`) e, no envio, os ids viram campos `mention_ids`. Imagem colada ou arrastada sobe para `POST /api/v1/uploads` e entra no texto como `![nome](/api/v1/attachments/<id>)`; a rota junta aos do "Anexar" (campos `attachment_ids`) os ids do texto que ainda são envios da pessoa (`_uploads_in_text`); uma imagem citada, copiada da descrição ou de outra tarefa, já está vinculada e só fica no texto. A exibição é do filtro `markdown` (`web/markdown.py`): `html: False`, links em outra aba, sem `javascript:`, e só imagens desse endereço (uma de fora aparece como texto, para não rastrear quem abre o chamado).
- **Campos com comportamento** (`_fields.html` + `chamado.js`, por atributos `data-*`): data e hora que acompanham o relógio até o ajuste (`*_ajustado`), tempo hh:mm com a lista de horários sugeridos (`<datalist>`, mostrada pelo `app.js`), anexos que sobem na hora (a 1ª etapa do docs/11 §11.4), pessoas em etiquetas e o cliente buscado por HTMX (`/clientes/opcoes`). Os relatórios também carregam o `chamado.js`, pelas etiquetas dos filtros (sem editor, o Tiptap não vem).
- **Trechos por HTMX sem templates parciais:** a rota devolve a página inteira e o `hx-select` escolhe o trecho: os responsáveis do grupo escolhido no registro (`/chamados/novo?grupo=`), a tarefa em edição ou a confirmação da remoção (`/chamados/{n}?editar=` / `?remover=`) e os membros do grupo de destino da transferência (`?team_id=`), e os relatórios (`#relatorio`). As parciais são a lista de clientes e o trecho de presença (`tickets/_presence.html`), perguntado a cada 20 s: renderizar a página inteira com essa frequência seria pesado.
- **Painel lateral das telas de administração:** lista ou árvore, botão **Novo** e edição no macro `side_panel()` (`_ui.html`), um `<dialog>` aberto pelo endereço (`?novo=1`, `?editar=<id>`). Os links (`panel_link()`) trocam só o `#painel` pelo HTMX e põem o endereço na barra; o `app.js` abre o painel quando ele chega (`data-abre-ao-carregar`) e, ao fechar, volta o endereço ao da lista (`data-volta`). Salvar recarrega a lista com o aviso; erro devolve a página com o painel aberto e o que foi digitado.
- **Expediente nas telas** (`web/work_hours.py`, macros em `admin/_expediente.html`): Configurações mostra as vigências da instalação e grava uma nova a partir de uma data, com os feriados (`set_work_hours`); os painéis de grupo e de usuário têm a seção Expediente: as vigências, o que vale hoje e de onde vem (`Calendar.source`: próprio, do grupo X ou da instalação), o aviso de quem está em dois ou mais grupos com expediente (a lista de usuários marca essas pessoas) e "Nova vigência a partir de", com a opção "sem expediente próprio" (POST `…/expediente`, que chama `work_hours.set_schedule`). No painel do usuário os campos ficam dentro do formulário dele e apontam o formulário do expediente por `form="…"` (um formulário não fica dentro de outro).
- **Prévia das cores (Configurações):** o formulário pede a própria página com as três cores digitadas (`hx-get` com `hx-params`, sem o token CSRF na URL) e troca só a `#previa`; a paleta sai do `palette.py`, sem outra cópia em JavaScript.
- **Relatórios:** `/relatorios` sai sem os números (o título, as abas, os filtros, o cabeçalho com os downloads, que não dependem deles) e, no lugar dos blocos, um esqueleto do tamanho deles (`#blocos`, com os ids `bloco-<i>` para onde a paginação rola e `aria-busy`) que pede `/relatorios/blocos` com a mesma consulta (`hx-trigger="load"`, `hx-select="#blocos"`); essa é a mesma página com os blocos calculados, e quem está sem JavaScript chega a ela pelo link do `<noscript>`. A rota chama `reports.service.resolve` (o mesmo que a dependência da API), `reports_blocks.scopes` e `builder.run` para cada bloco do modelo aberto (`aba`: um de `BUILTINS` ou o id de um modelo da pessoa; sem `aba`, o modelo inicial dela); o escopo é decidido ali, então a tela não usa `requires`, e o erro da API (ex.: 403 ao forçar outra pessoa) aparece na tela. Os gráficos são macros em SVG (`reports/_charts.html`, com a área sob a linha e a linha de referência tracejada, `Block.area` e `Block.reference`, calculada no `block_view`) que imitam o `BarChart`/`ColumnChart` da SPA, mais a linha: uma série, só os tokens de série (`chart-1` a `chart-4`, a cor do bloco pelo macro `series`, e `chart-before`, 4.2), ponta arredondada e base reta, a dica de cada coluna em CSS (`group-hover`/`group-focus`), sem JavaScript. **Filtros do modelo:** sem nenhum filtro na URL valem os salvos (os que deixaram de valer para a pessoa ficam de fora, com aviso); o formulário sempre manda o período, então mexer num filtro passa a valer o da URL, e num modelo da pessoa aparece **Salvar filtros** (`/relatorios/modelos/{id}/filtros`), com **Restaurar filtros salvos** (o modelo sem filtro na URL). No cabeçalho, à vista, só esses dois e o menu Baixar; **Editar modelo** (nos modelos da pessoa), **Salvar como modelo** e **Organizar abas** ficam no menu **Modelo** (o mesmo `<details data-menu>` do Baixar). **Abas:** na ordem da pessoa (`State.tabs`, de `saved.arrange`), sem as escondidas, menos a aberta; sem `aba`, abre a inicial (`State.initial`). A descrição do modelo aberto (`reports_state.description_of`: a do catálogo, `relatorios.descricoes.*`, nos prontos) fica abaixo das abas e no PDF; a de cada aba vai no `title` dela (nos modelos da pessoa, lida direto do JSON salvo, sem converter cada configuração). Organizar abas é um `<dialog>` com um formulário comum (`POST /relatorios/abas`, com CSRF, em `reports_editor.py`): `ordem` (as abas na ordem), `mostrar` e `acao` (`subir-<k>`/`descer-<k>` gravam e voltam com `organizar=1`, que reabre o diálogo por `data-abre-ao-carregar`; `salvar` só grava), e volta à aba e aos filtros com o aviso; um id que não é aba da pessoa responde 404. As abas ficam logo abaixo do título; debaixo dos filtros, "Filtrado por" lista cada valor escolhido com o × que o tira, e **Limpar filtros** tira todos mantendo a aba e o período (sem o período valeriam os salvos). **Editor** (`/relatorios/modelos/novo?base=<aba>&<filtros>`, `/relatorios/modelos/{id}/editar`): campos `b<i>-visual`, `b<i>-agrupar`, `b<i>-medida(s)`…, lidos de `request.form()`; adicionar, remover, mover e mudar as escolhas de um bloco (menos os textos, para não apagar o que se digita no campo seguinte) são POST com `acao` pelo HTMX (`hx-select="#editor"`, `hx-sync` cancela o pedido anterior), que refazem o formulário sem salvar; só `acao=salvar` grava (o modelo novo leva o período e os filtros da tela, em campos escondidos). Cada bloco mostra a prévia (`reports_editor._previews`): o mesmo `block_view` e o macro `block` (`_blocks.html`) da tela, `inert` e sem o CSV, com o período e os filtros da tela (modelo novo) ou os salvos (ao editar); os dados vêm pelo mesmo `scopes`, sem a comparação; um bloco que o `check_block` recusa mostra o erro no lugar; no modelo para o cliente, nada. **Período e filtro de cada bloco:** `reports_blocks.scopes` dá o `Scope` de cada bloco: o período (o da tela ou o próprio, `Block.period`, calculado por `relative_period`), os filtros efetivos (os da tela restritos pelos do bloco, `builder.narrow`, conferidos pelo `service.resolve`; os que saíram do alcance ficam de fora, com o aviso), a comparação sobre esse período e a query da URL do detalhar e da lista de chamados. Os blocos com o mesmo período e os mesmos filtros efetivos são um grupo, e o `service.facts` vem uma vez por grupo (e outra no período comparado), com o `builder.needs` dos blocos do grupo juntos; na tela, no PDF, no CSV de um bloco e na prévia do editor. Um bloco cujo filtro não tem nada em comum com o da tela não consulta e mostra o aviso no lugar. No editor, o período é um select e o filtro, as etiquetas da tela (`b<i>-grupo`…) numa seção recolhida; pôr ou tirar uma etiqueta dispara o evento `etiquetas` (`chamado.js`), que refaz o formulário. **Blocos:** todo bloco fica num cartão (o macro `frame` do `_blocks.html`: a mesma borda, sombra e espaçamento, `id="bloco-<i>"` e `scroll-mt-4`) com o mesmo cabeçalho (`block_head`): o título, o período (e o de comparação, quando o bloco compara; `block_view` monta o `period`) e, à direita, o menu de ações do bloco (`block_menu`, um `<details data-menu>`; hoje só o CSV, e não nos cartões nem na prévia do editor). Os gráficos são `figure` com o cabeçalho no `figcaption`; as tabelas guardam o `caption`. Na grade de duas colunas, os gráficos ocupam meia linha e os outros a linha inteira; o último de uma sequência ímpar de gráficos também (`reports_blocks.wide`, que o esqueleto usa igual), para não sobrar meia linha vazia; a largura escolhida no bloco (`Block.width`) vale mais que essa regra. As colunas ocupam 3/5 da faixa delas (até 2,5rem) e os rótulos das barras quebram em até duas linhas. As tabelas rolam dentro da caixa quando passam de 70% da tela (`max-h-[70vh] overflow-auto`, que também dá a rolagem lateral), com o cabeçalho fixo (`sticky`, preso a esse contêiner) e os números à direita; a lista de tarefas mostra 200 por página (`pagina<i>` na URL, por bloco; os links trocam o `#relatorio` e rolam até a lista). O CSV de um bloco é `/relatorios/csv?…&bloco=<i>` e o PDF do modelo (ou, num modelo para o cliente, o relatório dele) é `/relatorios/pdf?…` (tela, não API), com a mesma auditoria. **Modelo para o cliente** (`ReportConfig.audience == "client"`): a tela mostra a prévia no lugar dos blocos, e só com um cliente no filtro: uma folha A4 (macro `client_sheet`: proporção e margens do A4, papel branco também no modo escuro pelos tokens `paper-*`, as cores do `model_pdf`, e a fonte `font-paper`, a Helvetica do PDF) com o logotipo das Configurações (`branding.logo_url`), o título, o cliente, o período, os totais, os chamados e o rodapé com a data de geração; os textos vêm do `client_preview`, o mesmo que o PDF usa (a abertura e as observações do `ClientSpec`, com `whitespace-pre-line`, e as colunas escolhidas, com as chaves em `keys` para alinhar as horas e as datas), mas a folha cresce com a lista, sem as quebras de página. Os filtros da URL chegam às rotas pela dependência `Params` (os mesmos nomes do formulário, inclusive `comparar` e `dias`). **Comparar:** com `comparar=anterior` (o `1` dos links antigos vale o mesmo) ou `comparar=ano` (o mesmo período do ano anterior, `State.comparison`) e algum bloco que compara (`reports_blocks.compared`: cartões, tabela, colunas, linha), a rota lê também o `Facts` do período comparado, só com as partes desses blocos (o CSV de um bloco também, e ganha o valor de antes e a variação de cada medida); os cartões mostram a variação (com a seta ▲/▼, o "subiu"/"caiu" para o leitor de tela e a cor da direção boa da medida, `builder.GOOD_DIRECTION`: `green-fg` na boa, `red-fg` na ruim, `muted` nas neutras), a tabela ganha uma coluna Δ por medida (a regra do `_change`; nos cadastros, a linha do mesmo valor, no tempo, a da mesma posição; "Outros" e sem base, vazio) e as colunas e a linha por período, a série de antes mais apagada (`Point.before`, alinhada pela posição), com a legenda e o valor de antes na dica. Barras, colunas empilhadas e colunas por cadastro ou idade ficam sem série (a mesma posição não é o mesmo valor; as empilhadas já têm duas partes). **Detalhar:** cada linha, barra, coluna ou ponto leva um link para `/relatorios` com o filtro daquele valor (`reports_blocks._drill`); o período clicado leva o de antes em `origem` (um relativo, um mês da lista ou `de_ate`, só no personalizado e fora da regra "sem nenhum filtro"), e a tela mostra a trilha com o link que volta a ele; cada número de medida de chamado, para `/relatorios/chamados?medida=…` (a lista desses chamados, 200 na tela e o CSV com todos, com `formato=csv`, auditado). O período pode ser relativo (`semana-atual`, `mes-atual`, `ultimos-30-dias`, `trimestre-anterior`, `ultimos-12-meses`…, calculado por `builder.relative_period` a cada abertura: o link continua valendo; `ultimos-n-dias` leva os N em `dias`, e a origem do detalhar, `ultimos-n-dias:N`), um mês da lista ou duas datas. As setas ao lado do período andam um do mesmo tamanho (`previous_period`/`next_period`; no "ano até hoje" e num personalizado de 1º de janeiro até um dia do mesmo ano, as mesmas datas do ano vizinho), viram um mês da lista ou o personalizado e não passam de hoje; o personalizado tem atalhos (esta semana, semana passada, este mês, mês passado). Grupo, pessoa, cliente (com "Sem cliente") e status são etiquetas (`chips`); pôr ou tirar uma aplica o filtro (`aplicarFiltro` no `chamado.js`; o `app.js` não envia na troca do select das etiquetas). O cliente não vem na página (são milhares): a etiqueta dele é uma busca (`client_chips`, que reaproveita o combobox do `client_picker`) em `/relatorios/clientes` (`service.client_choices`: "Sem cliente" e 50 clientes pelo nome, inclusive os desativados, sem os já escolhidos); a tela lê as opções sem os clientes (`service.choices`) e só os nomes dos escolhidos (`service.client_labels`), que também conferem o filtro salvo que deixou de valer. A `GET /reports/options` da API continua com todos. **Sem recarregar:** o formulário (`hx-get`, `delay:600ms` para juntar as escolhas seguidas, `hx-push-url`, `hx-sync="this:replace"`), as abas, o resumo dos filtros e os links de detalhar (`hx-boost`) trocam o `#relatorio` (cabeçalho, filtros, abas e blocos: o cabeçalho e o intervalo dependem dos filtros) com `hx-select`; os links da lista de chamados e os downloads continuam links comuns. Enquanto carrega, o `#relatorio` ganha `htmx-request` (os resultados esmaecem, `in-[.htmx-request]`) e `aria-busy`; a troca traz o esqueleto, que pede os números (o indicador do `#relatorio` continua até eles chegarem); depois, o `#relatorio-aviso` (`aria-live`, fora da região) avisa, só quando os números chegam (não na primeira abertura), e o HTMX devolve o foco ao campo pelo `id`. Uma resposta que chega depois de outra escolha não troca a tela (o `chamado.js` conta os envios do formulário e compara com os de quem pediu, `requestConfig.elt`), e o pedido dos números de antes de uma troca é cancelado (`htmx:abort`). O Voltar recarrega o endereço (`historyCacheSize: 0`). **Impressão** (o Imprimir do navegador): somem o menu lateral, a barra do topo e o espaço em volta (regras do `input.css` presas ao `#relatorio`, só nesta tela), as abas, o formulário, os botões, os menus dos blocos, as dicas, o indicador de carregamento e os × do "Filtrado por" (as classes `print:hidden`); fica uma linha só da impressão com o modelo e o período (`printed`), os blocos não quebram no meio (`print:break-inside-avoid`), as tabelas saem inteiras (sem a rolagem de 70vh) e os gráficos com as cores (`print-color-adjust: exact`). O menu Baixar tem o PDF do modelo (`/relatorios/pdf`, em todas as abas) e links GET para `/api/v1/reports/csv` (a tabela da aba, nos prontos de horas, e todas as tarefas) com os mesmos filtros e o `locale` da pessoa. O "Expediente usado" (`reports_blocks.work_hours_line`) vai na tela e no cabeçalho do PDF quando algum bloco usa a hora extra (`uses_overtime`): `service.schedule_use` diz o que valeu no período (o da instalação, com as vigências que começaram nele, os grupos cujo expediente valeu para alguém, com quantas pessoas, e quem teve o próprio), só das pessoas ao alcance de quem vê (as do filtro de pessoa, ou ela e as dos grupos que supervisiona; tudo, com `report.view_all`) e com o nome só dos grupos que ela vê nos relatórios (os outros, juntos, como "outro grupo"); sem expediente de pessoa ou de grupo, nenhuma consulta a mais. `service.describe_use` monta o texto com os textos de quem chama (`relatorios.expedientes.*` na tela, `model_pdf.USE_TEXTS` no PDF da API), até `NAMES_LISTED` nomes.
- **Ações do chamado:** cada botão da lateral é um formulário (POST com `csrf_token`) que chama a função da API e volta ao chamado com o aviso (`_act`). Erro numa tarefa nova ou na edição devolve a página com o texto preenchido (422), sem perder o que foi escrito.
- **Kanban (`/quadro`):** os chamados de que a pessoa é responsável (principal ou não) e, do supervisor, também os dos grupos que supervisiona, com o filtro por responsável; o admin vê todos (`tickets.service.board`). Concluídos e cancelados só de um mês, escolhido no topo, à esquerda do responsável (mês atual ou passado, no horário da máquina; `?mes=passado`): os concluídos pelo `closed_at` e os cancelados pelo `canceled_at`. No mês passado, o topo ganha à esquerda (o mês e o responsável não saem do lugar) os campos "Concluir em" e "Cancelar em" (`?concluir_em=`, `?cancelar_em=`; só dias do mês passado, o último de início), e o cartão solto numa dessas colunas (`data-data-de`) leva o dia do campo às 23:59 em `conclusao_data`/`conclusao_hora`, que a rota de status repassa como `finished_at`. Mudar um campo não recarrega o quadro: o `quadro.js` só o põe no endereço, que vira a `volta`. No máximo 500 cartões (os mais antigos, com aviso). Uma coluna por status na ordem das Configurações, os cancelados por último (fundo `bg-danger/20`); cada coluna vai, no mínimo, até o pé da tela. O cartão mostra o cliente (empresa pelo nome fantasia, se houver; as outras telas usam a razão social), o responsável principal com "+N" para os outros (todos os nomes no `title`) e a data da última alteração e leva, escondido, o formulário de status do detalhe com `volta` para o quadro e os status permitidos em `data-destinos` (as mesmas regras do seletor do detalhe); o `quadro.js` só aceita soltar nessas colunas, preenche o status e envia, sem confirmação (também para cancelar). Mudar o status só se faz arrastando (sem teclado nem toque; para isso, o detalhe do chamado).
- **Colisão (docs/10 §10.6):** os formulários de status, cliente e "Marcar como entregue" levam o `etag` em `versao`, repassado como `If-Match`; no 412, a tela volta atualizada com o aviso `chamado.mudou`. O cabeçalho do detalhe inclui `_presence.html` (`hx-get` em `/chamados/{n}/presenca?desde=…`, `every 20s` e `visibilitychange`): quem mais está vendo e quantas tarefas novas chegaram. Com a aba escondida o pedido é cancelado (`chamado.js`): quem esconde a aba sai da lista em até 45 s (abrir o chamado numa aba de fundo ainda conta por esse tempo). Sem sessão, essa rota é a exceção ao redirecionamento: responde 286 com `HX-Reswap: none` (o HTMX para de perguntar e não troca nada), em vez de levar ao login e apagar o texto do editor. Essa rota passa pela visibilidade, mas não grava a visita nem audita. O "Adicionar tarefa" leva `visto_ate` (a data da última tarefa mostrada): se chegou tarefa de outra pessoa depois, não grava e devolve a página com ela à vista e o texto preservado (422); o envio seguinte passa.
- **Telas:** `/login`, `/sair`, `/esqueci-senha`, `/convite/{token}`, `/redefinir-senha/{token}`, `/trocar-senha`, `/idioma`, `/`, `/chamados` (com `/chamados/status-em-massa`), `/chamados/novo`, `/chamados/{n}` (e as ações em `/chamados/{n}/...`), `/quadro`, `/clientes/opcoes`, `/admin/clientes` (com `/novo` e `/{id}`), `/admin/usuarios`, `/admin/tokens`, `/admin/grupos`, `/admin/configuracoes` (com as ações de cada um; o expediente em `/admin/usuarios/{id}/expediente`, `/admin/grupos/{id}/expediente` e `/admin/configuracoes/expediente`), `/relatorios` (com `/relatorios/csv`, `/relatorios/pdf`, `/relatorios/chamados` e `/relatorios/modelos`: novo, editar, salvar, filtros, excluir) e `/meus-tokens` (com `/{id}/revogar`).

### 3.12 Worker, outbox e fila de tarefas (`modules/jobs/`)

Fila própria no PostgreSQL ([ADR 0003](docs/adr/0003-postgresql.md); a biblioteca Procrastinate foi avaliada e descartada em 2026-10-21: schema fora do Alembic, pool próprio e sem outbox).

```
ação no chamado ─► add_event() ─► ticket_events + outbox   (mesma transação: rollback desfaz os dois)
                                                │
chamados worker, a cada volta:                  ▼
  1. relay()     outbox ─► HANDLERS ─► jobs     (lote com SKIP LOCKED; tarefas e processed_at juntos)
  2. schedule()  rotinas do dia ─► jobs         (dedup_key: uma por dia, mesmo com dois workers)
  3. run_next()  jobs ─► TASKS                  (uma tarefa por vez; sem trabalho, espera 2 s)
```

- **Outbox** (`outbox`): `event_type` e `payload` (`ticket_id`, `actor_user_id`, `mention_ids` quando houver menção, `via` quando veio de fora da interface e, em `data`, o payload do evento). Os de chamado vêm do `add_event()`; o `comment.created`, só do comentário comum (`add_comment`): o comentário de uma ação vai no evento dela (`comment_id`). Por que não ler o `ticket_events`: ele só aceita inserção (não dá para marcar o que foi processado) e um cursor por `id` pularia eventos de transações que fazem commit fora de ordem.
- **Repasse** (`service.relay`): cada evento vai ao handler do seu tipo (`worker.HANDLERS`, hoje os de `notifications/handlers.py`), que cria as tarefas com `service.enqueue()`. Um handler que falha é desfeito (savepoint), o erro fica em `outbox.error` e no log, e os outros eventos seguem. Evento sem handler só é marcado.
- **Tarefas** (`jobs`, `worker.TASKS`): `async def tarefa(db, settings, args)`, numa sessão própria (faz o próprio commit). Enquanto roda, a linha fica travada (`FOR UPDATE SKIP LOCKED`): outro worker a pula, e se o processo cair a transação é desfeita e a tarefa volta sozinha para a fila. Não há status "rodando". A entrega é "pelo menos uma vez".
- **Falha:** volta para a fila com espera de 30 s, 2 min, 8 min e 32 min (`retry_delay`), com o erro em `last_error`; na 5ª (`max_attempts`) fica `failed` e vai para o log.
- **Rotinas** (`worker.ROUTINES`, no horário da máquina): `attachments.purge` às 03:00 e `jobs.cleanup` às 03:30 (apaga tarefas `done` e eventos processados há mais de 7 dias, `failed` há mais de 30 e as `Idempotency-Key` com mais de 24 h). A `dedup_key` (`attachments.purge:2026-10-21`) é única: dois workers não agendam a mesma rotina, e um worker que sobe depois do horário a roda na hora. No lugar do advisory lock sugerido no docs/03, porque ele sozinho não lembraria se a rotina do dia já rodou.
- **Encerramento:** SIGTERM (o `systemctl stop`) ou SIGINT terminam a tarefa em curso e saem. Um erro de banco derruba o processo, e o systemd o sobe de novo (`Restart=on-failure`).
- **Serviço:** `ticketflow-worker.service` acompanha o `ticketflow.service` (`PartOf` e `WantedBy=ticketflow.service`): sobe, para e reinicia junto com ele, mas é um processo à parte. Rodar dentro do uvicorn foi descartado: o `--reload` e os reinícios da API cortariam tarefas no meio, e um travamento de um derrubaria o outro.

### 3.13 Notificações por e-mail (`modules/notifications/`)

Regras em [docs/10 §10.10](docs/10-chamados.md#1010-notificações). Os handlers (`handlers.HANDLERS`, registrados no worker) transformam cada evento do outbox em e-mails, já montados no idioma de quem recebe, e cada e-mail vira uma tarefa `notifications.send_email` (`tasks.py`), que só envia (`Mailer.deliver`: a falha do SMTP sobe e a fila tenta de novo).

| Evento | Motivo → quem recebe |
|--------|----------------------|
| `ticket.created` | `mentioned` (mencionados), `assigned` (responsáveis), `new_in_team` (membros do grupo, se `teams.notify_on_new = 'email_all_members'`) |
| `ticket.assigned`, `ticket.assignees_changed` | `assigned` (quem entrou) |
| `ticket.transferred` | `assigned` (novo responsável), `transferred` (membros do grupo de destino) |
| `ticket.status_changed` | `mentioned` (mencionados no comentário da mudança, em qualquer uma); entrando num status `closed`: `closed` (observadores e quem registrou); saindo de um, menos para outro `closed` ou um `canceled`: `reopened` (responsáveis e observadores) |
| `comment.created` | `mentioned`, `comment` (responsáveis e observadores) |

- **Um e-mail por pessoa por ação:** vale o primeiro motivo da lista do handler (menção, atribuição, o resto). Quem causou o evento, quem está inativo, foi excluído ou não tem e-mail não recebe.
- **Texto simples**, com o comentário do evento (o da ação ou o comentário novo), se houver, e o link `APP_BASE_URL/chamados/<número>`. Assunto: `[#1234] Título: motivo`.
- Ainda sem preferências por pessoa (F2-S6-01): todos recebem tudo da tabela.
- Convite, redefinição e bloqueio continuam enviados na hora (`Mailer.send`, que só registra a falha no log).

### 3.14 Servidor MCP (`modules/mcp_server/`)

Assistentes de IA (Claude Code e outros clientes MCP) consultam e operam os chamados como ferramentas. Plano maior em [docs/06](docs/06-integracao-ia.md).

- **Transporte:** Streamable HTTP em `/mcp`, sem estado (`stateless_http`) e com respostas em JSON: cada POST é independente, sem sessão MCP no servidor. SDK oficial `mcp` (2.x, `MCPServer`).
- **Quem age:** o dono do token de API (3.1), com `Auth(via="mcp")`: as mesmas permissões, a mesma visibilidade e o histórico com `via: "mcp"`. A rota (`Endpoint`) recusa sem token válido (401, `WWW-Authenticate: Bearer`); cada ferramenta confere o token de novo, na própria sessão do banco (`call()`). Token `read` só usa as ferramentas de leitura.
- **Ferramentas:** leitura (`list_tickets`, `get_ticket` com as tarefas, `get_ticket_history`, `list_options` com status e grupos, `search_clients`) e escrita (`create_ticket`, `add_task`, `change_status`, que é o `set_status`, `assign_ticket` com `mode` `main` (o `POST /assign`) ou `add` (mais um responsável, o `PUT /assignees`), `transfer_ticket` e `cancel_ticket`, a única com `destructiveHint`; cancelar um já cancelado devolve o estado, sem erro; o `change_status` recusa um status cancelado e indica o `cancel_ticket`, para não ser o atalho sem confirmação). Erro de validação volta como "Dados inválidos: <campos>", sem os valores. Elas chamam os services e `tickets/queries.py`, como a API; a `HTTPException` vira `ToolError`, traduzida para o idioma da pessoa. O `get_ticket` audita o acesso a confidencial, mas não grava a visita (o aviso de novidade continua para a pessoa).
- **Repetição:** as de escrita que registram algo (`create_ticket`, `add_task`) aceitam `request_id`: a mesma chamada devolve o primeiro resultado, guardado em `idempotency_keys` com a chave `mcp:<request_id>` (mesmo dono e a mesma regra do 3.1, inclusive a retomada de uma chamada parada há mais de 5 min). `change_status` repetido não muda nada.
- **Instância por lifespan:** o SDK só deixa rodar o gerenciador de sessões uma vez por instância; `running(app)` cria o servidor no lifespan do app (os testes reabrem o lifespan a cada teste), e a rota fixa `/mcp` repassa para `app.state.mcp_app`.
- **DNS rebinding:** a proteção do SDK fica desligada (`TransportSecuritySettings`). Ela confere o `Host` e o `Origin` contra uma lista, e aqui não protegeria nada a mais: o ataque usa o navegador da vítima, que manda os cookies do site, mas não o `Authorization`, e sem token a rota responde 401. Ligada, a lista de endereços teria de acompanhar cada instalação (o do `APP_BASE_URL`, o IP, o 127.0.0.1).
- **Conectar:** a tela `/meus-tokens` mostra o comando do Claude Code (`claude mcp add --transport http ticketflow <APP_BASE_URL>/mcp --header "Authorization: Bearer tf_…"`).

---

## 4. Telas, tema e idiomas

A interface é toda renderizada pelo servidor (3.11, [ADR 0011](docs/adr/0011-interface-web-no-servidor.md)). A SPA em Vue que existia antes saiu em 2026-10-19 (WEB-06, [docs/19](docs/19-migracao-da-interface.md)); o histórico dela fica no git.

### 4.1 Telas

| Rota | Tela | Acesso |
|------|------|--------|
| `/login`, `/esqueci-senha`, `/convite/{token}`, `/redefinir-senha/{token}` | Entrar, senha esquecida, convite e redefinição (`card.html`) | Público |
| `/trocar-senha` | Troca obrigatória da senha provisória | Logado |
| `/chamados` | Filas em abas com contadores (Meus, Aguardando, Acompanhando, Todos), filtro de grupo (status e responsável na aba Todos), total de horas e lápis (abre o chamado) em cada linha e, para supervisor e admin, seleção de vários chamados com mudança de status (janela flutuante no pé da tela). Aba e filtros na URL (`?aba=todos&grupo=…&status=…&responsavel=…&q=…`); sem aba, abre em Meus (ou em Todos, para quem não tem grupo). É a tela inicial: `/` redireciona para cá | Logado |
| `/chamados/novo` | Registro | `ticket.create` |
| `/chamados/{número}` | Detalhe: linha do tempo, tarefas, ações da lateral | Quem vê o chamado (403/404 na própria tela) |
| `/admin/clientes` | Lista com busca (nome, CPF/CNPJ, e-mail), no menu Administração | `client.view` (grupo Administradores) |
| `/admin/clientes/novo`, `/admin/clientes/{id}` | Cadastro em três colunas (dados, contato, endereço); sem `client.manage`, só leitura | `client.manage` / `client.view` |
| `/admin/usuarios`, `/admin/grupos` | Cadastros, com o painel lateral | `admin.users` / `admin.organization` |
| `/admin/tokens` | Tokens de API ativos de todas as pessoas (inclusive os vencidos e os de quem está inativo), com o filtro por pessoa e o botão Revogar | `admin.users` |
| `/meus-tokens` | Tokens de API da pessoa (no menu do usuário): criar com nome, acesso (leitura ou leitura e escrita) e validade (30, 90 ou 365 dias), ver o último uso, revogar. O valor aparece uma vez, na resposta da criação, sem redirecionar | Logado |
| `/relatorios` | Abas com os modelos prontos (Produtividade, Clientes, Horas extras, Chamados) e os da pessoa, cada um uma lista de blocos (cartões, barras, colunas, colunas empilhadas, linha, tabela, lista de tarefas) com o CSV de cada um e os links de detalhar; comparar com o período anterior; filtros de período (relativo, mês ou datas), grupo, pessoa, cliente e status (vários valores); Salvar como modelo, Editar modelo, Salvar filtros; menu Baixar (PDF e CSV da aba nos prontos, CSV de todas as tarefas). Editor de modelo em `/relatorios/modelos/…`; a lista de chamados de um número em `/relatorios/chamados`. O filtro de grupo/pessoa só aparece com opções (`GET /reports/options`) | Logado (a API limita os números) |
| `/admin/configuracoes` | Idioma, cores, logotipo, status dos chamados e expediente | `admin.settings` |

Os itens do menu lateral (`side_nav()` em `_ui.html`) aparecem conforme `page.can(permissão)`. O botão "Novo chamado" e a busca global ficam no cabeçalho (`app.html`): `1234` ou `#1234` abre o chamado, texto abre a aba Todos com `q`. Endereço desconhecido fora de `/api` mostra a página de erro (`error.html`).

### 4.2 Tema e cores

- `static/css/input.css` define os tokens `--tf-*` em `:root` (claro) e `.dark` (escuro); o Tailwind os expõe como cores (`@theme inline`). Os macros de `_ui.html` usam só esses tokens (`bg-surface`, `text-muted`, `bg-primary`…), **nunca cores diretas** ([docs/17](docs/17-identidade-visual.md)).
- O modo escuro é a classe `dark` no `<html>`, aplicada pelo `static/js/tema.js` antes da primeira pintura (escolha guardada no navegador em `tf-tema`; menu do tema no `app.js`). Os tokens escuros (o `.dark` do `input.css`, o `html.dark` da folha do `palette.py`, a variante `dark:` e o `color-scheme`) valem só em `@media screen`: a impressão sai sempre no tema claro.
- **Cores personalizadas:** `web/palette.py` deriva os tokens que dependem da identidade a partir das 3 cores das Configurações, em OKLCH, mantendo o matiz e ajustando o tom até cumprir os contrastes da WCAG AA ([docs/17 §17.3](docs/17-identidade-visual.md#173-contraste-wcag-21-aa)). Com as cores padrão, usa a paleta original escolhida à mão (`DEFAULT_PALETTE`). A folha vai embutida no `<head>` (`<style id="tf-cores">`).
- **Mapa de calor:** `heat-1` a `heat-5` (`palette._heat_scale`): o matiz da `primary`, do tom quase do fundo até ela, em passos iguais de luminosidade e saturação; um teste confere que cada tom se afasta mais do fundo e que o último tem 3:1, em qualquer trio de cores. O "sem nada" é a célula vazia, só com a borda. O PDF usa os do modo claro (`model_pdf.Series.heat`).
- **Séries dos gráficos:** `chart-1` é a `primary` (no `input.css`, `var(--tf-primary)`); `chart-2` (as horas extras das colunas empilhadas e a linha das barras + linha), `chart-3`, `chart-4` (as cores que um bloco pode escolher, `Block.color`) e `chart-before` (o período anterior) são derivadas no `palette.py` com 3:1 sobre `surface` e `bg`. A `chart-2` a `chart-4` saem de uma lista de matizes (azul, verde-azulado, violeta, âmbar; depois os mesmos mais longe do fundo, `_FARTHER`): cada uma é o primeiro candidato que se distingue da `primary` e das já escolhidas (`distinct`: distância OKLab ×100 de 15, e de 8 com protanopia e deuteranopia simuladas, como o validador da skill `dataviz`; um teste confere as quatro, duas a duas, na paleta original, nas combinações e nas prontas); a `chart-before` é a `primary` mais clara e menos saturada. O PDF do modelo usa as do modo claro (`model_pdf.Series.named`, pelo nome do token).
- Cores de status e do botão destrutivo **não** dependem das 3 cores.
- **Sombra dos blocos:** todo bloco da página (tabela, painel, seção de formulário, cartão; o `rounded-lg border border-border bg-surface`) leva `shadow-md`, para dar profundidade. O que flutua sobre a página (menus, avisos, janelas e a barra do status em massa) usa `shadow-lg` ou `shadow-xl`.

### 4.3 Idiomas

- Os catálogos ficam em `web/locales/pt-BR.json` e `web/locales/en.json`, com **as mesmas chaves e os mesmos marcadores** (`{nome}`); o `tests/unidade/test_web_i18n.py` confere.
- **Nenhum texto fixo** nos templates: tudo via `t("chave", nome=…)`. Sem a chave no idioma, vale o português; sem ela em nenhum, aparece a própria chave.
- O idioma é o da pessoa ou o padrão do sistema (3.11). Datas e números são formatados no servidor (`web/formatting.py`); o fuso é o da máquina (`core/timezone.py`: o `TZ` do ambiente ou o `/etc/localtime`, lido ao subir), e a página o passa ao `chamado.js` em `<meta name="fuso">`.

---

## 5. Contrato da API

- A API JSON (`/api/v1`) continua para integrações e agentes de IA; os assistentes que falam MCP usam `/mcp` (3.14), com o mesmo token. O contrato sai dos modelos Pydantic: `/api/docs` (Swagger) e `chamados openapi -o arquivo` (3.10).
- Campos novos são aditivos. Mudança incompatível só numa nova versão da API (`/api/v2`), conforme o [docs/05](docs/05-api.md).
- As telas chamam as funções das rotas, os services e `tickets/queries.py` direto (3.11), sem HTTP: os testes das telas (`test_web_*.py`) cobrem esse uso.

## 6. Segurança (resumo do que está implementado)

| Tema | Como |
|------|------|
| Senhas | Argon2id; mínimo de 8 caracteres; lista de senhas comuns (`identity/senhas_comuns.txt`) |
| Sessão | Cookie `tf_sessao` (HttpOnly, SameSite=Lax, Secure em produção); só o hash fica no banco; expira por inatividade e por prazo máximo; desativar o usuário encerra as sessões |
| Tokens de API | `Authorization: Bearer`; só o hash no banco; escopo `read`/`write`; fora da administração; validade de 30, 90 (padrão) ou 365 dias na tela (365 no `chamados token create`); revogação pela própria pessoa (`/meus-tokens`), pela administração (`/admin/tokens`), pelo `chamados token revoke` e ao desativar ou excluir a pessoa |
| CSRF | Token sincronizado: cookie `tf_csrf` (legível pelo JavaScript da página) conferido com o hash da sessão; nas telas, num campo escondido (`csrf_token`) ou no header `X-CSRF-Token` (HTMX e envio de anexos) |
| Força bruta | Limite por IP na tabela `login_ip_failures` (UNLOGGED; vale para todos os workers, com uma trava por IP para as tentativas simultâneas) + espera progressiva e bloqueio da conta (`ratelimit.py`) |
| Permissões | Sempre no backend (3.4); a interface só esconde botões |
| Conteúdo | Markdown sem HTML bruto; logotipo sem SVG e conferido pelos bytes; `X-Content-Type-Options: nosniff` |
| Cabeçalhos | CSP, HSTS, X-Frame-Options e Referrer-Policy no nginx (`deploy/nginx.conf`) |
| Rastro | `audit_log` e `ticket_events` (só inserção) |

## 7. Testes e verificação

| Onde | Ferramenta | Como |
|------|------------|------|
| `backend/tests/` | pytest + **PostgreSQL real** (`TEST_DATABASE_URL`, banco `chamados_test`) | Uma pasta por área (abaixo). O banco de teste só desce até a base e sobe de novo quando `migrations/` muda (a marca fica no comentário da `alembic_version`); cada teste começa com as tabelas vazias (`DELETE`, na ordem das FKs dos modelos) e os status da migração. O app sobe uma vez por sessão. Auxiliares no `conftest.py` (`criar_usuario`, `entrar`, `grupo`, `criar_categoria`, `criar_cliente`, a fixture `cenario`, `outra_sessao`, `consultas`, `FakeMailer`) e no `apoio.py` (os usados por mais de uma pasta: `registrar`, `criar_token`, `rodar`…) |
| `web/static/js/` | ainda sem teste automático | O JavaScript das telas foi conferido à mão no jsdom durante a migração; a cobertura entra com os testes ponta a ponta (Playwright, F1-S5-04) |

| Pasta | O que testa | Tempo |
|-------|-------------|-------|
| `tests/unidade/` | Regras puras, sem banco nem app: `test_permissions` (matriz do docs/08), `test_regras_chamados` (ações × situação), paleta, formatação, fuso, catálogos de idioma | ~2 s |
| `tests/api/` | API REST, services e servidor MCP, com banco (inclusive `test_visibilidade`, as 6 regras) | ~40 s |
| `tests/telas/` | Telas do servidor, pelo HTML que devolvem (`test_web_*.py`). **Todo teste que passa por uma tela fica aqui** | ~30 s |
| `tests/banco/` | Migrações sobem e descem; comandos `chamados db` | ~7 s |
| `tests/worker/` | Outbox, fila, worker e notificações por e-mail | ~10 s |

Durante a tarefa, roda-se a pasta (ou o arquivo) do que mudou: `uv run pytest tests/telas`.

`scripts/check.sh` faz o papel do CI ([docs/12 §12.3](docs/12-processo-de-desenvolvimento.md#123-verificação-local-no-lugar-do-ci)):

| Modo | Roda |
|------|------|
| `--rapido` (hook de pre-commit) | ruff nos arquivos do commit; procura segredos |
| padrão | + mypy e os testes que a mudança desde o último commit afeta, no PostgreSQL 17: só `web/` (e docs) → `tests/unidade` e `tests/telas`; só testes → as pastas deles; qualquer outra coisa (ou nada mudou) → todos, com cobertura (mínimo de 80%) |
| `--completo` | + todos os testes no PostgreSQL 17, com cobertura, e no 16; auditoria de dependências |

### 7.1 Benchmark (`backend/bench/`)

Mede o que as pessoas fazem no dia a dia com a massa do RNF-01 ([docs/02](docs/02-requisitos.md#requisitos-não-funcionais): p95 < 300 ms nas leituras com 50 mil chamados) e confere se a resposta está **certa**. Fica fora do pytest e do `check.sh` (leva minutos); roda-se à mão, antes e depois de mexer numa consulta, numa tela pesada ou num índice:

```
cd backend
uv run python -m bench                  # todos os cenários
uv run python -m bench --filtro busca   # só os que têm "busca" no nome (sem diferenciar maiúsculas)
uv run python -m bench --refazer        # gera a massa de novo
uv run python -m bench.carga            # 5 pessoas ao mesmo tempo, com 1 e com 4 workers
```

| Arquivo | O que faz |
|---------|-----------|
| `massa.py` | Gera a massa em SQL, no banco `chamados_bench` (`BENCH_DATABASE_URL`): 50 mil chamados em 3 anos, ~200 mil tarefas, 60 pessoas em 8 grupos, 3 mil clientes, categorias em 3 níveis (com uma confidencial), observadores, transferências e um chamado com 150 tarefas. É a mesma a cada vez (`setseed`) e só é refeita quando as migrações, a `VERSAO` dela ou o `--chamados` mudam (a marca fica no comentário da `alembic_version`, como no banco de teste). Planta palavras e um cliente que a busca precisa achar |
| `cenarios.py` | Cada cenário: a pessoa (admin, supervisora, agente), a requisição, a meta (300 ms nas leituras, nas telas e nas escritas; 2 s no PDF e no CSV) e a **conferência**: a resposta contra um oráculo em SQL escrito à parte, inclusive a visibilidade do docs/08 §8.4. Mudou uma regra de visibilidade, de fila ou de busca: o oráculo muda junto |
| `carga.py` | Teste de carga: 5 pessoas ao mesmo tempo, sem pausa entre os cliques (a admin no relatório de 12 meses, as outras em listas, busca, quadro, chamado e tarefas), num **uvicorn de verdade** que ele sobe num socket Unix (sem porta, sem colidir com o serviço) e derruba no fim; compara números de workers (`--workers 1,4`). Mostra quanto as ações leves esperam pela pesada. Cada requisição numa conexão nova, como o nginx faz com o uvicorn |
| `__main__.py` | Sobe o app no próprio processo (`TestClient`, sem uvicorn), entra com cada pessoa, aquece, mede até 30 vezes (no máximo ~10 s por cenário), conta as consultas SQL por requisição e confere. Imprime p50, p95, máximo, a meta e a diferença do p95 para a execução anterior (guardada em `bench/resultados/`, fora do git). Sai com erro se algum cenário passar da meta ou responder errado |

As escritas usam uma pessoa e um grupo só delas ("Escritas"): não mudam as filas que os outros cenários medem. Os tempos dependem da máquina; compare execuções na mesma máquina, sem os testes rodando ao mesmo tempo.

## 8. Execução

| Ambiente | Como |
|----------|------|
| **Desenvolvimento, terminais** | PostgreSQL nativo (17 na 5432, 16 na 5433; numa máquina nova, `scripts/preparar-maquina-dev.sh`); `uv run uvicorn chamados.main:create_app --factory --reload` (porta 8000) e `scripts/css.sh --watch` (o CSS das telas). Ver o [README](README.md#como-rodar-desenvolvimento) |
| **Desenvolvimento, e-mails** | O `instalar-servico-dev.sh` instala o Mailpit (`mailpit.service`): SMTP em `127.0.0.1:1025`, tela em `http://IP:8025`, e `SMTP_HOST=localhost` no `/etc/ticketflow/env`. Por terminais, sem `SMTP_HOST`, os e-mails vão para o log |
| **Desenvolvimento, worker** | Com o serviço: o `instalar-servico-dev.sh` instala o `ticketflow-worker.service` (o da produção, que acompanha o `ticketflow`) com um drop-in que o roda pelo `watchfiles`, reiniciando o worker quando um `.py` de `backend/src` muda. Por terminais: `uv run chamados worker` (com o `backend/.env`), em primeiro plano; Ctrl+C encerra |
| **Desenvolvimento, serviço** | `sudo scripts/instalar-servico-dev.sh`: modo de desenvolvimento, sem build, atrás do nginx em `https://IP` (80 redireciona para 443; certificado autoassinado em `/etc/ticketflow/tls`). O nginx manda tudo para o `ticketflow.service` (a unit da produção com um drop-in: uvicorn em `127.0.0.1:8001` com `--reload` em `backend/src`). O `ticketflow-css.service` gera o CSS das telas (`scripts/css.sh --watch`) e o `ticketflow-worker.service`, o worker (com o `watchfiles`). Aplica as migrações e, de instalações antigas, desativa e apaga o `ticketflow-frontend.service` (Vite) |
| **Produção** | Ubuntu 24.04, systemd (`deploy/*.service`), uvicorn com 4 workers (para 8 núcleos), nginx com HTTPS, PostgreSQL 17. Atualização por `scripts/deploy.sh`. O backup não faz parte do programa: fica com quem administra o servidor. Passo a passo no [manual do servidor](docs/18-manual-do-servidor.md) |

Quem reinicia o serviço é sempre a pessoa responsável, nunca um script ou o Claude Code ([CLAUDE.md](CLAUDE.md)). Na máquina de desenvolvimento não é preciso: o `--reload`, o `watchfiles` do worker e o `ticketflow-css.service` pegam as mudanças, que aparecem ao recarregar a página. Na produção, templates e CSS mudam assim que o `deploy.sh` termina; o código Python, só depois do `systemctl restart`.

---

## 9. Regras da arquitetura

1. **Toda leitura de chamados passa por `ticket_visibility_filter`**: nas buscas, nos relatórios, nos anexos, em tudo o que vier.
2. **Toda ação em chamado passa por `allowed_actions`** (`service.require`). Rota nova de chamado sem essa checagem é defeito.
3. **Toda alteração de chamado** (campos, status, responsável, grupo, observadores, edição e remoção de tarefa) **gera um evento** em `ticket_events` e no `outbox` (`add_event()` grava os dois), na mesma transação. O histórico nunca é alterado. Os comentários novos já são o próprio registro e vão só para o outbox.
4. **Administração e login vão para o `audit_log`** com antes e depois.
5. **Cadastros não são apagados**, só desativados.
6. **A interface não decide permissões**; usa `allowed_actions` e `page.can()` só para mostrar botões. Tela do servidor que chama rota de administração da API exige a permissão com `requires(P.X)`.
7. **Nada de cor direta** nos templates: só tokens. Nada de texto fixo: só i18n, nos dois idiomas.
8. **A API é contrato para integrações**: campos novos são aditivos; mudança incompatível só em `/api/v2` (5).
9. **Mensagens de erro da API em português**, com a tradução no catálogo de `core/i18n.py`.
10. **Só SQL que roda no PostgreSQL 16 e 17.**
11. **Migração revisada e reversível**; o schema muda só por migração.

## 10. O que ainda não existe

| Peça | Onde entra | Referência |
|------|------------|------------|
| Ocultar anexo, lista de tipos configurável pelo admin, miniaturas, antivírus | `attachments` | Sprint 5 e depois, [docs/11](docs/11-anexos-e-arquivos.md) |
| Status personalizados, ocultar comentário, testes ponta a ponta (Playwright) | — | Sprint 5 |
| Tela da auditoria | A API `GET /admin/audit-log` já existe | Sprint 5 |
| MFA, sessões, aprovações, sino de notificações | — | Fase 2 |
| Webhooks, IA (o sistema chamando modelos: triagem, resumo, sugestão) | `jobs` (webhooks), um módulo `ai` | Depois da v1.0, [docs/06](docs/06-integracao-ia.md) |

## 11. Receitas

**Nova rota de API**
1. Schema de entrada e saída (Pydantic) no módulo; rota no `router.py` com `CurrentAuth` ou `require(P.X)`.
2. Regra de negócio no `service.py`; se for chamado, `service.require(auth, ticket, "acao")` e `add_event()`.
3. Mensagem de erro em português → tradução no catálogo `EN` de `core/i18n.py`.
4. Testes de integração **e de permissão** (quem pode e quem não pode).

**Nova tabela ou coluna**
1. Modelo em `modules/<módulo>/models.py`; se o módulo é novo, importar em `db/models.py`.
2. Migração por autogenerate, revisada à mão, com `downgrade`.
3. Os testes esvaziam toda tabela que tem modelo (`db/models.py`); uma tabela sem modelo faz a sessão de testes falhar.

**Nova ação num chamado**
1. Incluir a ação em `rules.allowed_actions` (e em `TRANSITIONS`, se mudar o status).
2. Linha nova nos testes tabelados de `tests/unidade/test_regras_chamados.py`.
3. Service + rota + evento (o histórico fica no banco e na API; a tela não mostra eventos).

**Nova tela** (3.11)
1. Rota em `web/<área>.py` com `PageDep` ou `LoggedPageDep`, chamando a função da API ou o service (nenhuma regra na tela); router incluído em `web/__init__.py`. Se chama rota de administração da API, `requires(P.X)`.
2. Template em `web/templates/<área>/`, estendendo `app.html` (com menu) ou `card.html`; só os macros de `_ui.html` e tokens de cor. Campos de um modo que não está em uso vão num `<fieldset disabled>`.
3. Textos em `web/locales/pt-BR.json` **e** `en.json`.
4. Classes novas do Tailwind: `scripts/css.sh` (ou o `ticketflow-css.service`) gera o `app.css` de novo.
5. Teste em `tests/telas/test_web_<área>.py`, conferindo o HTML, os redirecionamentos e as permissões (inclusive quem tenta entrar sem a permissão).

**Nova tarefa ou rotina do worker** (3.12)
1. Função `async def tarefa(db, settings, args)` que faz o próprio `commit`; registrada em `worker.TASKS` com um nome `modulo.acao`.
2. Rotina diária: o nome também em `worker.ROUTINES`, com o horário (da máquina). Evento que vira tarefa: um handler `async def handler(db, settings, event)` em `worker.HANDLERS` que chama `service.enqueue()`.
3. A tarefa pode rodar mais de uma vez (entrega "pelo menos uma vez"): ela precisa aguentar isso.
4. Teste chamando `service.run_next` com a tarefa (veja `tests/worker/test_fila.py`).

**Nova ferramenta MCP** (3.14)
1. Função `@server.tool(annotations=READ ou WRITE)` em `mcp_server/server.py`, com descrição (docstring) e `Field(description=…)` nos parâmetros: é o que o modelo lê.
2. Dentro de `async with call(ctx, write=…) as (db, auth, locale)`, só service ou `tickets/queries.py` (nenhuma regra na ferramenta). Se registra algo, `request_id` com `once()`.
3. Teste em `tests/api/test_mcp.py` (`ferramenta()` e `erro()`), inclusive quem não pode.

**Nova permissão**
1. Código em `P` (`core/permissions.py`) e nos papéis (`ROLES`); se depende de supervisão, em `SUPERVISOR`.
2. Migração que atualiza `roles.permissions` dos papéis do sistema, e o teste `test_papeis_da_migracao_batem_com_o_catalogo` passa a comparar com essa migração.
3. Linha nova na matriz de `test_permissions.py` e no [docs/08](docs/08-organizacao-e-permissoes.md#83-catálogo-de-permissões).
