# Arquitetura do TicketFlow

Guia da **estrutura do código como ela é hoje**: onde fica cada coisa, como as peças conversam e quais regras não podem ser quebradas. Leia antes de mexer no projeto e atualize este documento quando a estrutura mudar (módulo novo, camada nova, regra nova).

- **Por que** cada tecnologia foi escolhida e o que está **planejado** para depois: [docs/03-arquitetura.md](docs/03-arquitetura.md) e os [ADRs](docs/adr/).
- **O que** o sistema faz (regras de negócio): [docs/08](docs/08-organizacao-e-permissoes.md), [docs/10](docs/10-chamados.md) e os demais documentos em [docs/](docs/).
- **Em que ponto está** cada item do roadmap: [TAREFAS.md](TAREFAS.md).

Situação em 2026-10-13: Fase 0, Sprint 2, Sprint 3, as Configurações (F1-S3-11), o cadastro de clientes (ligado aos chamados) e, da Sprint 4, as filas, a busca e os anexos prontos (o "Pegar o próximo" saiu junto com a fila de não atribuídos, em 2026-10-15). A seção 10 lista o que ainda não existe.

Em 2026-10-17 começou a migração da interface da SPA em Vue para telas renderizadas no servidor, com Jinja2, HTMX e Tailwind ([ADR 0011](docs/adr/0011-interface-web-no-servidor.md)). O login, as telas de senha, o layout (menu, cabeçalho, menu do usuário) e a lista de chamados já são do servidor; as demais continuam na SPA até migrarem (3.11).

---

## 1. Visão geral

```
navegador ── HTTPS ──► nginx ──► uvicorn (ticketflow.service) ──► PostgreSQL 17 (ou 16)
                                   │
                                   ├─ /api/*    API REST (FastAPI)
                                   ├─ telas do servidor (Jinja2 + HTMX, web/) e /static
                                   └─ /*        SPA compilada (frontend/dist), até o fim da migração
```

- **Um processo**, um **monólito modular** em Python (FastAPI). Ele serve a API e também a interface web, **na mesma origem**: sem CORS e com o cookie de sessão funcionando sem configuração extra ([ADR 0010](docs/adr/0010-producao-systemd.md)). A interface está migrando da SPA em Vue compilada para telas renderizadas pelo próprio FastAPI (3.11).
- **Um banco**, o PostgreSQL, que guarda tudo: dados, sessões, auditoria, histórico, configurações e o logotipo. Não há Redis, fila externa nem armazenamento de objetos.
- **API-first:** a interface só conversa com a API; toda regra de negócio e toda decisão de permissão ficam no backend.
- **Uma instalação por empresa** ([ADR 0005](docs/adr/0005-instalacao-por-empresa.md)): não existe `tenant_id`.

Os anexos ficam em disco, em `FILES_DIR` (3.5.1). Ainda **não existe** o worker (fila de tarefas e e-mails assíncronos), que entra na Sprint 4 (seção 10).

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
│   ├── migrations/        Alembic: env.py e versions/0001…0028
│   ├── src/chamados/      código (seção 3); as telas do servidor ficam em web/ (3.11)
│   └── tests/             pytest com PostgreSQL real (seção 7)
├── frontend/              SPA (Vue 3, TypeScript, Vite, Tailwind 4, Reka UI); sai ao fim da migração
│   ├── public/tema.js     aplica tema, idioma e cores antes da primeira pintura
│   └── src/               código (seção 4)
├── scripts/               check.sh, install-hooks.sh, deploy.sh, backup.sh, instalar-servico-dev.sh, css.sh,
│                          preparar-maquina-dev.sh (Ubuntu 24.04 novo pronto para desenvolver)
└── deploy/                units do systemd (app, worker, backup) e nginx.conf
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
│   ├── text.py          texto dos formulários: optional_text() e required_text()
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

1. `main.create_app()` cria a aplicação, registra os tratadores de erro, inclui os routers de cada módulo sob `/api/v1`, devolve 404 em JSON para qualquer `/api/*` desconhecido e, por último, serve `frontend/dist` (rotas desconhecidas devolvem o `index.html`, para o roteamento da SPA).
2. **Autenticação** (`identity/deps.py`, `get_auth`): lê o cookie de sessão, confere o CSRF em métodos que alteram dados, **relê o usuário e os grupos a cada requisição** (mudanças de papel valem na hora) e monta o `Actor`. Com a senha provisória (`must_change_password`), só três rotas funcionam até a troca.
3. **Rota → service:** rotas simples (cadastros) fazem o trabalho no próprio `router.py`; quando há regra de negócio, a rota delega a um `service.py`. Não existe camada de *repository*: os services usam o SQLAlchemy diretamente.
4. **Transação:** cada operação faz um único `commit` no fim. Histórico (`ticket_events`) e auditoria (`audit_log`) entram na **mesma transação** da mudança.
5. **Erros:** qualquer `HTTPException(status, "mensagem em português")` vira Problem Details (`{"type", "title", "status", "detail"}`) em `core/errors.py`, com `title` e `detail` traduzidos para o idioma do `Accept-Language` (3.6). Erros de validação viram 422 com a lista `errors`; exceções não tratadas viram 500 e vão para o log.

### 3.2 Configuração (`config.py`)

Variáveis de ambiente (em produção, `/etc/ticketflow/env`; em desenvolvimento, `backend/.env`):

| Variável | Padrão | Uso |
|----------|--------|-----|
| `DATABASE_URL` | `postgresql+psycopg://chamados:chamados@localhost:5432/chamados` | Banco |
| `LOG_LEVEL`, `LOG_FORMAT` | `INFO`, `json` | Logs (`console` em desenvolvimento) |
| `APP_BASE_URL` | `http://localhost:5173` | Endereço usado nos links dos e-mails |
| `COOKIE_SECURE` | `true` | Cookie só em HTTPS (desligar sem HTTPS) |
| `SESSION_IDLE_HOURS`, `SESSION_MAX_DAYS` | `8`, `7` | Expiração das sessões |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_STARTTLS`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | sem `SMTP_HOST` | Sem SMTP, os e-mails vão para o log |
| `FRONTEND_DIST` | `frontend/dist` | Pasta da SPA compilada |
| `FILES_DIR` | `/var/lib/ticketflow/files` | Anexos (só o usuário do serviço acessa; entra no backup com o banco) |

### 3.3 Módulos

| Módulo | Arquivos | Responsabilidade | Rotas |
|--------|----------|------------------|-------|
| `identity` | `models` (User, UserSession, AuthToken), `router` (login, `/me`), `admin_router` (usuários), `deps`, `sessions`, `passwords`, `tokens`, `ratelimit`, `service` (convites e e-mails), `schemas` | Login, sessões e CSRF, senhas (Argon2id), convite e redefinição, força bruta, usuários, idioma da pessoa | `/auth/*`, `/me`, `/users` |
| `organization` | `models` (Role, Team, TeamMember, Department), `router` | Papéis, grupos e membros, setores atendidos | `/teams`, `/departments` |
| `catalog` | `models` (Category, TicketStatus, ResolutionCode), `router` | Árvore de categorias (até 3 níveis; sem tela desde que saíram dos chamados), status por `kind`, códigos de resolução | `/categories`, `/statuses`, `/resolution-codes` |
| `clients` | `models` (Client), `router`, `documents` (CPF, CNPJ alfanumérico, telefone, CEP) | Cadastro de clientes pessoa física e jurídica, com contato e endereço; sem exclusão (inativa) | `/clients` |
| `tickets` | `models`, `schemas`, `router`, `service`, `rules`, `visibility` | Chamados, comentários, observadores, atribuição (um ou mais responsáveis), transferência, transições e histórico | `/tickets/*` |
| `system` | `models` (SystemSetting), `router`, `service`, `work_hours` (expediente) | Configurações da instalação: idioma padrão, cores, logotipo, expediente; idioma efetivo de um usuário | `/branding`, `/admin/settings`, `/work-hours` |
| `audit` | `models` (AuditLog), `service` (`record()`), `router` | Auditoria de login e administração | `/admin/audit-log` |
| `attachments` | `models` (Attachment), `router`, `service` (vínculo, lista, limpeza), `files` (tipos aceitos, limites, nome saneado), `storage` (disco) | Anexos dos chamados: envio em duas etapas, download com a permissão do chamado | `/uploads`, `/attachments/{id}` |
| `reports` | `schemas`, `service` (escopo, cálculo, horas fora do expediente), `pdf` (ReportLab), `router` | Relatórios de horas: por pessoa, cliente e dia, horas extras e PDF (3.7.2) | `/reports`, `/reports/options`, `/reports/pdf` |
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
- **As permissões em vigor vêm do código** (`ROLES` em `core/permissions.py`, pelo código do papel do usuário). A tabela `roles` também guarda a lista de cada papel (cópia gravada pela migração 0002, mais as permissões acrescentadas depois em `NEW_PERMISSIONS` das migrações, como a 0010 e a 0015, menos as retiradas em `REMOVED_PERMISSIONS`, como a 0016; um teste confere), mas ainda não é lida: ela prepara os papéis personalizados de depois da v1.0.

### 3.5 Chamados (`modules/tickets/`)

- **Identificação:** `id` interno (bigint), `public_id` (UUID, exposto) e `number` (sequência `ticket_number_seq`, começa em 1000). As rotas aceitam o número ou o UUID (`/tickets/1234`).
- **Status:** a tabela `ticket_statuses` tem um `kind` fixo (`open`, `waiting`, `delivered`, `closed`, `canceled`, `approval`); `delivered` é o Entregue, a revisão do supervisor. As regras usam só o `kind`, e cada mudança vai para o status padrão do `kind` de destino.
- **Transições:** `rules.TRANSITIONS` define, para cada ação (`wait`, `resume`, `close`, `reopen`, `cancel`), de quais `kind` se sai, para qual se vai, quem pode e se exige comentário ou código de resolução. O comentário da transição é gravado como comentário do chamado; o de conclusão leva `is_solution`.
- **Sem prioridade:** chamados não têm prioridade, impacto nem urgência (removidos na migração 0016). Eventos antigos com essas mudanças continuam no histórico.
- **Status personalizados:** o admin cria (nome + `kind`: open, waiting, delivered, closed, canceled), renomeia, ordena (`PUT /statuses/order`) e remove em Configurações (`admin.settings`). O `kind` não muda depois de criado. Cada `kind` precisa de ao menos um status; ao remover, os chamados vão para o padrão do mesmo `kind`, e se o removido era o padrão o próximo da lista assume. O primeiro status criado de um `kind` vira o padrão. Ações em `audit_log` (`ticket_status.*`).
- **Status no formulário:** além das transições do fluxo, a ação `set_status` (quem tem `ticket.transition` no grupo) escolhe qualquer status no registro (`status_id`, padrão Pendente) e na edição, sem comentário nem código de resolução. `_apply_status` acerta `closed_at` e conta a reabertura ao sair de um `closed`. O evento é `ticket.status_changed` sem `action`. Para um status `closed`, a ação também exige `set_status_closed`, que todo `set_status` tem, menos quando o status atual é de revisão (`kind` `delivered`, "Entregue"): aí só o supervisor do grupo ou o admin.
- **Categoria:** opcional e fora dos formulários do chamado (continua na API e no cadastro). Sem categoria, o grupo é obrigatório e o tipo é `incident`; `category_id: null` no PATCH tira a categoria.
- **Início:** `started_at` é quando o trabalho começou. Sem valor no registro, vale a hora do registro; a pessoa pode informar outra (nunca no futuro, com 5 minutos de folga para o relógio) e alterar depois, com evento no histórico. Na interface, `DateTimeField` acompanha a hora atual até ser mudado.
- **Cliente e contato:** para quem é o trabalho. `client_id` é **obrigatório** no registro e só aceita cliente ativo (um cliente inativado depois continua nos chamados antigos); no PATCH troca, mas `null` é recusado (422). A obrigação fica só na API: o banco aceita chamados antigos sem cliente (os relatórios os agrupam como "sem cliente"). O **contato** (quem pediu) é texto livre e fica em `beneficiary_name`, a antiga "pessoa atendida". Na interface, o `ClientPicker` busca em `GET /clients/options` (qualquer pessoa logada; só clientes ativos, só o id e o nome, busca pelo nome ou nome fantasia). O setor atendido (`department_id`) continua na API, mas saiu da interface.
- **Histórico:** fica só no banco e em `GET /tickets/{id}/events`; a linha do tempo da tela mostra só o registro e os comentários (decisão do usuário, 2026-10-13). Cada mudança chama `service.add_event()`, que grava em `ticket_events` com `payload` (antes/depois, com id **e nome** das referências na data do evento). A tabela **só aceita inserção**: uma trigger da migração 0004 recusa `UPDATE` e `DELETE`.
- **Responsável obrigatório:** todo chamado tem responsável (`tickets.assignee_id` NOT NULL desde a migração 0028); não há fila de não atribuídos nem "devolver à fila". O registro exige `assignee` (`"me"` ou um membro ativo do grupo), `POST /assign` só troca de responsável, e a transferência exige `assignee_id`, um membro ativo do grupo de destino.
- **Mais de um responsável:** `tickets.assignee_id` é o responsável principal e `ticket_co_assignees` guarda os demais (só no registro, `co_assignee_ids`, membros ativos do grupo). Para regras, visibilidade (regra 3), fila Meus, aviso de novidade e o filtro por responsável, todos contam igual (`visibility.assigned_to`). Transferir tira os demais; trocar o principal os mantém. A interface envia quem registra como principal, se estiver na lista, senão a primeira pessoa.
- **Grupos que atuaram:** `ticket_teams` recebe o grupo na criação e a cada transferência; alimenta a regra 2 da visibilidade.
- **Tarefas (comentários):** o autor edita (texto, tempo, `done_at`) e remove (`DELETE`, só marca `deleted_at`; evento `comment.deleted` com o texto e o tempo) a qualquer momento. Toda leitura de comentários (lista, tempo gasto, busca, novidades, anexos do detalhe) ignora os removidos; a lista ordena por `done_at`.
- **Tempo gasto:** cada comentário (andamento) pode ter `time_spent_minutes` (opcional, 1 a 60 000), no comentar, na mudança de status (vai no comentário da transição; sem comentário, 422) e na edição (o valor anterior vai em `before_time_spent_minutes` do `comment.edited`). O detalhe traz `time_spent_minutes` (total) e `time_by_person` (soma por autor, `service.time_by_person`), mostrados na lateral.
- **Observadores e menções:** `ticket_watchers` (`kind` = `watcher` ou `mentioned`). As menções chegam em `mention_ids`: o texto guarda só "@Nome".
- **Lista:** ordenação padrão (mais antigo primeiro) com paginação por cursor (base64 de data e id). Filtros: `team`, `assignee` (`me` ou o id), `status` (kinds) e `q`.
- **Total de horas na lista:** cada item traz `time_spent_minutes` (`service.time_spent()`, subconsulta da soma das tarefas não removidas).
- **Status em massa:** `POST /tickets/bulk/status` (`numbers`, `status_id`; até 200). Cada chamado passa por `load` (visibilidade), pela ação `bulk` (`ticket.bulk`: supervisor do grupo ou admin) e por `_change_status` (as mesmas regras do `set_status`, inclusive a revisão). Os que falham voltam em `failed`, com o motivo traduzido; os demais mudam numa transação só.
- **Filas:** o parâmetro `view` da lista (`service.view_filter`): `mine` (sou o responsável, `open`/`waiting`/`delivered`), `waiting` (meus grupos, `waiting`/`delivered`), `watching` (sou observador, `open`/`waiting`/`delivered`) e `all` (tudo o que vejo). `GET /tickets/counts` conta as três primeiras numa consulta só.
- **Novidade:** comentário de outra pessoa depois da minha última visita (`has_news` em cada item da lista, mostrado como ícone ao lado do título; a aba Com novidades saiu em 2026-10-15). A visita fica em `ticket_reads` e é gravada pelo `GET /tickets/{id}` (`service.mark_read`). A reabertura exige comentário, por isso também vira novidade.
- **Busca (`q`):** `search_vector` (colunas geradas, índice GIN) em `tickets` (título peso A, descrição peso B) e em `ticket_comments`, na configuração `pt_br` (português sem acentos). Cada palavra vira prefixo (`impress:*`) e todas precisam aparecer. Também acha pelo número (`1234` ou `#1234`), pelo nome do cliente e pelo contato (`unaccent` + `ILIKE`). Passa pelo filtro de visibilidade como qualquer leitura.

### 3.5.1 Anexos (`modules/attachments/`)

- **Duas etapas** ([docs/11 §11.4](docs/11-anexos-e-arquivos.md#114-fluxo-de-envio-em-duas-etapas)): `POST /uploads` (multipart, campo `file`) guarda o arquivo sem dono e devolve o id; o registro, o comentário, a mudança de status e a edição (da descrição ou de um comentário) recebem `attachment_ids` e chamam `attachments.service.link()`. Só quem enviou vincula, e uma vez só; o que já está no mesmo lugar é ignorado (a edição manda de novo as imagens que o texto já tinha).
- **Enviar** exige `ticket.comment` ou `ticket.create`; o vínculo passa pelo `allowed_actions` da ação (comentar, editar…). **Baixar** (`GET /attachments/{id}`) passa por `tickets.service.load`, ou seja, pela visibilidade do chamado; um envio ainda sem dono só quem enviou baixa. Download de chamado confidencial vai para a auditoria.
- **Tipos** (`files.py`): lista fechada de extensões, conferidas pelos primeiros bytes (PNG, JPEG, PDF, ZIP dos formatos Office/ODF…; os de texto não podem ter byte nulo). O `content_type` gravado vem da extensão conferida, nunca do navegador. Zip, 7z, Office com macro, executáveis, html e svg são recusados.
- **Limites:** 25 MB por arquivo (413), 10 por envio, 200 MB por chamado.
- **Disco** (`storage.py`): `FILES_DIR/attachments/AAAA/MM/<uuid>`, gravado num temporário e renomeado; o nome original (saneado) e o SHA-256 ficam só no banco.
- **Download:** `inline` para imagens e PDF, `attachment` para o resto, com `X-Content-Type-Options: nosniff` e `Content-Security-Policy: sandbox`.
- **Limpeza:** `chamados attachments purge` apaga os envios sem dono há mais de 24 h.
- O detalhe do chamado traz `attachments` (do registro e de todos os comentários, com `comment_id`); a interface mostra cada anexo no seu comentário e todos na lateral.

### 3.6 Idiomas (backend)

- Idiomas: `pt-BR` (padrão) e `en` (`core/i18n.py`).
- **Mensagens:** são escritas em português no código. `core/errors.py` traduz `title` e `detail` pelo catálogo `EN` quando o `Accept-Language` pede inglês; a interface envia o idioma escolhido em toda chamada. Um teste percorre o código (AST) e falha se alguma mensagem de `HTTPException` não estiver no catálogo.
- **E-mails:** textos em `identity/service.EMAILS`, por idioma. O idioma é o de quem recebe: `users.locale` ou o padrão do sistema (`system.service.user_locale`).

### 3.7 Configurações (`modules/system/`)

- Tabela `settings` com chave e valor (jsonb). Sem a linha, vale o padrão. Chaves: `locale`, `colors` (`brand`, `neutral`, `background`), `logo` (imagem em base64, tipo e sha256) e `work_hours` (expediente: `weekdays` 0 = segunda, `start`, `end`, `holidays`; padrão seg–sex 08:00–18:00). O expediente é lido por todos (`GET /work-hours`) e gravado por `PUT /admin/settings/work-hours`.
- `GET /branding` é **público**: a tela de login também usa as cores, o logotipo e o idioma.
- O logotipo é servido por `GET /branding/logo?v=<hash>`, com cache permanente (o endereço muda quando a imagem muda). Só PNG, JPEG e WebP, conferidos pelos primeiros bytes; SVG é recusado porque pode conter scripts.
- O backend guarda só as **três cores**; a paleta inteira é derivada no frontend (4.6).

### 3.7.1 Clientes (`modules/clients/`)

- Pessoa física (`person`: CPF, RG, nascimento) ou jurídica (`company`: CNPJ, nome fantasia, inscrições estadual e municipal, pessoa de contato). Os campos do outro tipo ficam nulos.
- Obrigatórios: nome completo e CPF (PF) ou razão social, nome fantasia e CNPJ (PJ), mais CEP, cidade e UF (a API confere; o banco aceita cadastros antigos sem eles). O CPF/CNPJ é validado e único (restrição no banco); o nome também não repete (a API compara sem maiúsculas, acentos e espaços a mais).
- Documentos, telefones e CEP são gravados sem pontuação; a interface formata (`composables/documentos.ts`). O CNPJ aceita o formato alfanumérico (julho de 2026): mesmo cálculo dos dígitos, com o valor de cada caractere = ASCII − 48.
- A validação fica no router (`_clean`), com mensagens do catálogo de idiomas. O formulário envia o cadastro inteiro (`PUT`).
- Permissões: `client.view` e `client.manage`, que nenhum papel tem: valem só para membros do grupo **Administradores** (ativo; nome comparado sem maiúsculas, `CLIENT_MANAGERS_TEAM` em `core/permissions.py`), mesmo com papel Administrador. Renomear o grupo tira a permissão de todos. Os demais só escolhem o cliente pelo nome (`GET /clients/options`). A auditoria registra só **quais campos** mudaram, sem os dados pessoais.
- Ligação com os chamados: `tickets.client_id` (3.5).

### 3.7.2 Relatórios (`modules/reports/`)

- Regras de negócio em [docs/14 §14.7](docs/14-relatorios-e-indicadores.md#147-relatórios-de-horas-pedido-do-usuário-2026-10-15). Calculado na hora, sem tabela própria: as tarefas do período vêm numa consulta e as somas (pessoa, cliente, dia) e as horas extras saem em Python (`service.build`).
- **Escopo:** `service.resolve` confere os filtros (grupo e pessoa só os que a pessoa pode ver, senão 403) e `_own_or_supervised` restringe as linhas: `report.view_all` vê tudo; os demais, o próprio trabalho mais os chamados dos grupos supervisionados. Sempre junto com `ticket_visibility_filter`.
- **Hora extra:** `service.outside_minutes(done_at, minutos, expediente)`: a tarefa termina em `done_at`; conta o que fica fora da faixa do dia (em São Paulo), nos dias que não são de trabalho e nos feriados.
- **PDF:** `pdf.render` (ReportLab, fontes padrão do PDF, sem pacotes do sistema), no idioma do `Accept-Language`, gerado numa thread; cada download vai para o `audit_log` (`report.exported`).

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
| `0024` | `users.display_name`: o nome que aparece no sistema (o completo fica no cadastro) |
| `0025` | Sai a restrição única de `clients.document`: o mesmo CPF/CNPJ pode estar em mais de um cadastro |
| `0026` | Volta a restrição única de `clients.document` (desfaz a `0025`) |
| `0027` | `client.manage` sai dos papéis (passa a vir do grupo Administradores) |
| `0028` | `tickets.assignee_id` NOT NULL: todo chamado tem responsável |
| `0029` | `client.view` também sai dos papéis: o cadastro de clientes é só do grupo Administradores |

- **Convenções:** `bigint GENERATED ALWAYS AS IDENTITY` + `public_id uuid` nas entidades expostas; `timestamptz` sempre; nomes de constraint previsíveis (`db/base.py`); nada é apagado nos cadastros (só desativado: `is_active`).
- **Compatibilidade:** só recursos do PostgreSQL **16 e 17** (`check.sh --completo` testa nos dois).
- **Nova migração:** gerar com o autogenerate do Alembic a partir dos modelos, **revisar à mão** (sequences, triggers, cargas iniciais e índices parciais não são detectados) e conferir que o `downgrade` funciona. O teste `test_migrations` desce até a base e sobe de novo.

### 3.10 Comando `chamados` (`cli.py`)

| Comando | Faz |
|---------|-----|
| `chamados db upgrade [rev]` / `downgrade rev` / `current` | Migrações |
| `chamados admin create --email … --name …` | Cria um administrador e mostra o link para definir a senha (recuperação de acesso) |
| `chamados attachments purge` | Apaga os envios não vinculados há mais de 24 h (até o worker existir, rodar pelo cron) |
| `chamados openapi [-o arquivo]` | Exporta o contrato OpenAPI (usado pelo `pnpm gen:api`) |

### 3.11 Telas do servidor (`web/`, ADR 0011)

```
web/
├── __init__.py          router das telas (fora do OpenAPI), incluído em main.py antes da SPA
├── page.py              Page (sessão opcional, idioma, marca, can(), render), LoggedPage (exige
│                        login), Redirect, safe_next(), check_csrf(), flash()
├── auth.py              login, sair, esqueci a senha, convite, redefinição, troca obrigatória, idioma
├── tickets.py           / (vai para a lista), lista de chamados com as filas, status em massa
├── formatting.py        datas, "há 3 dias" e duração como o formato.ts (fuso de São Paulo)
├── i18n.py              translate(): os catálogos JSON da SPA (frontend/src/i18n) até a troca final
├── palette.py           paleta derivada das 3 cores (port do tema/paleta.ts, mesmos tons)
├── templating.py        ambiente Jinja2 e static() (endereço com a data do arquivo)
├── templates/           base.html, card.html (cartão sem menu), app.html (menu e cabeçalho),
│                        _ui.html (macros), _icons.html, auth/, tickets/
└── static/              css/input.css (→ app.css gerado), js/ (tema.js, app.js, vendor/htmx), fonts/
```

- **Sem regra na tela:** a rota da tela chama a função da rota da API (`identity.router.login(...)`) ou o service, e só monta o HTML. Os erros da API (`HTTPException`) viram a mensagem na tela, traduzida por `Page.api_message()`.
- **Sessão:** `get_page` lê o cookie `tf_sessao` (`load_session` + `session_auth`, as mesmas peças do `get_auth` da API). `LoggedPageDep` exige login (sem sessão, `/login?volta=…`) e, com a senha provisória, só abre `/trocar-senha` e `/sair`.
- **Idioma:** o da pessoa ou o padrão do sistema; nas telas sem login, o padrão. `t("chave", nome=…)` nos templates.
- **CSRF:** formulário que altera dados manda `csrf_token` (o valor do cookie `tf_csrf`) num campo escondido, conferido por `check_csrf()` com o hash da sessão. O login não precisa (ainda não há sessão).
- **Avisos:** `flash(response, ("success", texto))` antes de redirecionar; a próxima tela os mostra no canto (`toasts()` do `app.html`) e apaga o cookie `tf_aviso`. Os de sucesso somem em 5 s.
- **Botões por permissão:** `page.can("ticket.create")` só mostra ou esconde (menu lateral, Novo chamado, seleção em massa); quem decide é a rota.
- **JavaScript (`static/js/app.js`):** comportamento por atributos `data-*`, sem build: menus em `<details data-menu>`, `<dialog>` (`data-abre-dialogo`), formulário que aplica ao mudar (`data-envia-ao-mudar`), avisos e a seleção do status em massa. O HTMX busca trechos (`hx-select` sobre a página inteira que a rota devolve, sem templates parciais), como o "Carregar mais" da lista.
- **Redirecionamento:** `raise Redirect(url)` em qualquer ponto (inclusive nas dependências) vira 303. Endereços de volta passam por `safe_next()`, que só aceita caminhos deste site.
- **Cores:** `palette.stylesheet()` gera a folha das cores personalizadas, embutida no `<head>` (`<style id="tf-cores">`; a CSP aceita estilo embutido, não script). O tema claro/escuro fica no navegador (`tf-tema`, a mesma chave da SPA), aplicado pelo `tema.js` antes da primeira pintura.
- **CSS:** `scripts/css.sh` roda o Tailwind standalone (`pytailwindcss`, versão fixa no script) sobre `static/css/input.css` e procura classes só em `templates/` e `static/js/`. O `app.css` não vai para o git: o `deploy.sh` o gera, e em desenvolvimento o `ticketflow-css.service` (ou `scripts/css.sh --watch`) o gera de novo a cada mudança.
- **Convivência com a SPA:** o Vite repassa ao uvicorn os endereços já migrados (`server.proxy` no `vite.config.ts`, a lista entre parênteses), e as rotas da SPA para esses endereços usam o `ServerView.vue`, que recarrega a página. Migrar uma tela = criar a rota e o template aqui, acrescentar o endereço nessa lista e trocar o componente da rota da SPA por `NA_SERVIDOR` (ou apagar a rota, se a SPA nunca navega para ela).
- **Telas migradas:** `/login`, `/sair`, `/esqueci-senha`, `/convite/{token}`, `/redefinir-senha/{token}`, `/trocar-senha`, `/idioma`, `/` e `/chamados` (com `/chamados/status-em-massa`).

---

## 4. Frontend (`frontend/src/`)

A SPA está sendo substituída pelas telas do servidor (3.11, [ADR 0011](docs/adr/0011-interface-web-no-servidor.md)): tela nova vai para `web/`, e cada tela migrada sai daqui.

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
│   ├── relatorios.ts    relatórios, opções dos filtros, download do PDF e expediente
│   └── formato.ts (datas no fuso de São Paulo), useHead.ts, useToast.ts
├── views/               uma pasta por área: auth/, tickets/, clients/, reports/, admin/
├── components/
│   ├── ui/              design system: Button, TextField, SelectField, RadioGroup, DateTimeField, DurationField (hh:mm com lista), Modal, SidePanel, DataTable, badges…
│   ├── layout/          AppLayout (menu, cabeçalho), SideNav, UserMenu (idioma, sair), ThemeMenu, AppLogo
│   ├── admin/           StatusSettings (status dos chamados) e WorkHoursSettings (expediente), dentro de Configurações
│   ├── reports/         BarChart (barras horizontais) e ColumnChart (colunas no tempo): uma série, só tokens
│   ├── editor/          RichEditor (Tiptap → Markdown, @menções, imagens coladas), MarkdownView, markdown.ts
│   └── tickets/         TicketTimeline, CommentBox, TicketDetails, DeliverTicket, ClientPicker,
│                        AttachmentUploader (Anexar, arrastar e soltar), AttachmentList
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
- **Leitura** com TanStack Query: as chaves são `['chamados', filtro]` (uma por fila e filtros), `['chamados', 'contagens']`, `['chamado', numero]`, `['chamado', numero, 'comentarios']`, `['grupos']`, `['usuarios']`, `['setores']`, `['status']`, `['clientes', filtro]`, `['cliente', id]`, `['relatorios', filtro]`, `['relatorios', 'opcoes']`, `['expediente']`.
- **Escrita:** `useAlteracao(fn, chaves)` (admin) e `useAcaoNoChamado(numero, fn)` (chamados) fazem a mutação e invalidam as chaves afetadas.
- **Usuário logado:** `auth.me` vem do `/me` e guarda os grupos e as permissões. Telas que dependem dos grupos o releem (`auth.carregar()`), porque eles podem mudar depois do login.

### 4.3 Telas

| Rota | Tela | Acesso |
|------|------|--------|
| `/login`, `/esqueci-senha`, `/convite/:token`, `/redefinir-senha/:token` | No servidor (3.11): `ServerView.vue` recarrega a página | Público |
| `/trocar-senha` | Troca obrigatória da senha provisória, no servidor (3.11) | Logado |
| `/chamados` | No servidor (3.11). Filas em abas com contadores (Meus, Aguardando, Acompanhando, Todos), filtro de grupo (status e responsável na aba Todos), total de horas e lápis (abre o chamado) em cada linha e, para supervisor e admin, seleção de vários chamados com mudança de status (janela flutuante no pé da tela). Aba e filtros na URL (`?aba=todos&grupo=…&status=…&responsavel=…&q=…`); sem aba, abre em Meus (ou em Todos, para quem não tem grupo). É a tela inicial: `/` redireciona para cá | Logado |
| `/chamados/novo` | Registro | `ticket.create` |
| `/chamados/:numero` | Detalhe: linha do tempo, comentários, ações | Quem vê o chamado (403/404 na própria tela) |
| `/admin/clientes` | Lista com busca (nome, CPF/CNPJ, e-mail), no menu Administração | `client.view` (grupo Administradores) |
| `/admin/clientes/novo`, `/admin/clientes/:id` | Cadastro em três colunas (dados, contato, endereço); sem `client.manage`, só leitura | `client.manage` / `client.view` |
| `/admin/usuarios`, `/admin/grupos`, `/admin/setores` | Cadastros | `admin.users` / `admin.organization` |
| `/relatorios` | Relatórios: totais, abas Produtividade, Clientes e Horas extras (gráficos + tabelas), filtros de período, grupo, pessoa e cliente, botão Baixar PDF. O filtro de grupo/pessoa só aparece com opções (`GET /reports/options`) | Logado (a API limita os números) |
| `/admin/configuracoes` | Idioma, cores, logotipo, status dos chamados e expediente | `admin.settings` |
| `/dev/componentes` | Vitrine do design system | Só em desenvolvimento |

Os itens do menu lateral (`SideNav.vue`) aparecem conforme `auth.pode(permissão)`. O botão "Novo chamado" e a busca global ficam no cabeçalho (`AppLayout.vue`): `1234` ou `#1234` abre o chamado, texto abre a aba Todos com `q`.

### 4.4 Componentes

- `components/ui/` é o **design system** ([docs/17](docs/17-identidade-visual.md), [ADR 0008](docs/adr/0008-reka-ui.md)): componentes acessíveis sobre o Reka UI e estilizados só com os tokens (`bg-surface`, `text-muted`, `bg-primary`…), **nunca com cores diretas**.
- Telas de administração seguem o mesmo padrão: lista ou árvore, botão **Novo** e edição num `SidePanel`.
- Os componentes de chamado (`components/tickets/`) recebem o chamado por prop e decidem os botões só por `chamado.allowed_actions`.

### 4.5 Editor e Markdown

- Descrição e comentários são **Markdown** no banco. `RichEditor.vue` (Tiptap + `@tiptap/markdown`) edita visualmente e grava Markdown. Com `pessoas`, o `@` abre a lista de colegas, e `mencionados()` devolve os ids para `mention_ids`.
- `MarkdownView.vue` mostra o texto com `markdown-it` em `html: false`: HTML digitado aparece como texto e links `javascript:` são recusados. É o único `v-html` do projeto.
- **Imagens:** com `anexar`, o `RichEditor` envia a imagem colada ou arrastada (`POST /uploads`) e a insere como `![nome](/api/v1/attachments/<id>)`. Quem envia o formulário junta os ids do texto (`anexosNoTexto`) aos do `AttachmentUploader` em `attachment_ids`. O `MarkdownView` só mostra imagens desse endereço; uma imagem de fora aparece como texto (não é carregada, para não rastrear quem abre o chamado).
- O Tiptap (~150 kB gzip) fica num pedaço carregado só nas telas de chamado.

### 4.6 Tema e cores

- `assets/main.css` define os tokens `--tf-*` em `:root` (claro) e `.dark` (escuro); o Tailwind os expõe como cores (`@theme inline`). O modo escuro é a classe `dark` no `<html>` (`stores/theme.ts`; escolha do usuário no `ThemeMenu`).
- **Cores personalizadas:** `tema/paleta.ts` deriva os 13 tokens que dependem da identidade a partir das 3 cores das Configurações, em OKLCH, mantendo o matiz e ajustando o tom até cumprir os contrastes da WCAG AA ([docs/17 §17.3](docs/17-identidade-visual.md#173-contraste-wcag-21-aa)). Com as cores padrão, usa a paleta original escolhida à mão (`PALETA_PADRAO`).
- `stores/branding.ts` injeta a folha `<style id="tf-cores">` (`html:root{…}` e `html.dark{…}`, mais específicos que os do `main.css`) e guarda uma cópia no navegador para o `tema.js`.
- Cores de status e do botão destrutivo **não** dependem das 3 cores.

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
| CSRF | Token sincronizado: cookie `tf_csrf` legível pela SPA + header `X-CSRF-Token` conferido com o hash da sessão; nas telas do servidor, o mesmo token num campo escondido (`csrf_token`) |
| Força bruta | Limite por IP em memória (a API roda num processo só) + espera progressiva e bloqueio da conta (`ratelimit.py`) |
| Permissões | Sempre no backend (3.4); a interface só esconde botões |
| Conteúdo | Markdown sem HTML bruto; logotipo sem SVG e conferido pelos bytes; `X-Content-Type-Options: nosniff` |
| Cabeçalhos | CSP, HSTS, X-Frame-Options e Referrer-Policy no nginx (`deploy/nginx.conf`) |
| Rastro | `audit_log` e `ticket_events` (só inserção) |

## 7. Testes e verificação

| Onde | Ferramenta | Como |
|------|------------|------|
| `backend/tests/` | pytest + **PostgreSQL real** (`TEST_DATABASE_URL`, banco `chamados_test`) | A sessão de testes desce as migrações até a base e sobe de novo; cada teste começa com `TRUNCATE` (`conftest.py`). Auxiliares: `criar_usuario`, `entrar`, `grupo`, `criar_categoria`, `FakeMailer`. As telas do servidor são testadas pelo HTML que devolvem (`test_web_*.py`) |
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
| **Desenvolvimento, terminais** | PostgreSQL nativo (17 na 5432, 16 na 5433; numa máquina nova, `scripts/preparar-maquina-dev.sh`); `uv run uvicorn chamados.main:create_app --factory --reload` (porta 8000) e `pnpm dev` (porta 5173, repassa `/api` para a 8000). Ver o [README](README.md#como-rodar-desenvolvimento) |
| **Desenvolvimento, serviço** | `sudo scripts/instalar-servico-dev.sh`: modo de desenvolvimento, sem build, atrás do nginx em `https://IP` (80 redireciona para 443; certificado autoassinado em `/etc/ticketflow/tls`). O nginx manda `/api/` para o `ticketflow.service` (a unit da produção com um drop-in: uvicorn em `127.0.0.1:8001` com `--reload` em `backend/src`) e o resto, com o websocket da atualização automática, para o `ticketflow-frontend.service` (Vite em `127.0.0.1:5173`, `TF_HMR_PORT=443`), que repassa as telas do servidor ao uvicorn (3.11). O `ticketflow-css.service` gera o CSS das telas do servidor (`scripts/css.sh --watch`). Aplica as migrações |
| **Produção** | Ubuntu 24.04, systemd (`deploy/*.service`), nginx com HTTPS, PostgreSQL 17. Atualização por `scripts/deploy.sh`; backup diário por `scripts/backup.sh` (timer). Passo a passo no [manual do servidor](docs/18-manual-do-servidor.md) |

Quem reinicia o serviço é sempre a pessoa responsável, nunca um script ou o Claude Code ([CLAUDE.md](CLAUDE.md)). Na máquina de desenvolvimento não é preciso: o Vite e o `--reload` pegam as mudanças sozinhos. Na produção, o frontend compilado é servido direto da pasta e muda na hora; o backend só muda depois do `systemctl restart`.

---

## 9. Regras da arquitetura

1. **Toda leitura de chamados passa por `ticket_visibility_filter`**: nas buscas, nos relatórios, nos anexos, em tudo o que vier.
2. **Toda ação em chamado passa por `allowed_actions`** (`service.require`). Rota nova de chamado sem essa checagem é defeito.
3. **Toda alteração de chamado** (campos, status, responsável, grupo, observadores, edição e remoção de tarefa) **gera um evento** em `ticket_events`, na mesma transação. O histórico nunca é alterado. Os comentários novos já são o próprio registro.
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
| Worker, fila de tarefas e *outbox* (eventos → notificações) | Comando `chamados worker`; a unit `deploy/ticketflow-worker.service` já existe, mas só deve ser instalada quando o comando existir | Sprint 4, [docs/03](docs/03-arquitetura.md#eventos-de-domínio) |
| Notificações por e-mail dos chamados | Hoje só existem os e-mails de convite, redefinição e bloqueio, enviados na hora | Sprint 4 |
| Ocultar anexo, lista de tipos configurável pelo admin, miniaturas, antivírus | `attachments` | Sprint 5 e depois, [docs/11](docs/11-anexos-e-arquivos.md) |
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
3. Service + rota + evento (o histórico fica no banco e na API; a tela não mostra eventos).

**Nova tela** (no servidor, 3.11)
1. Rota em `web/<área>.py` com `PageDep` ou `LoggedPageDep`, chamando a função da API ou o service (nenhuma regra na tela); router incluído em `web/__init__.py`.
2. Template em `web/templates/<área>/`, estendendo `base.html` ou `card.html`; só os macros de `_ui.html` e tokens de cor.
3. Textos em `pt-BR.json` **e** `en.json` (`frontend/src/i18n/` até a troca final).
4. Se substitui uma tela da SPA: endereço no `server.proxy` do `vite.config.ts` e `NA_SERVIDOR` na rota da SPA.
5. Teste em `tests/test_web_<área>.py`, conferindo o HTML, os redirecionamentos e as permissões.

**Nova permissão**
1. Código em `P` (`core/permissions.py`) e nos papéis (`ROLES`); se depende de supervisão, em `SUPERVISOR`.
2. Migração que atualiza `roles.permissions` dos papéis do sistema, e o teste `test_papeis_da_migracao_batem_com_o_catalogo` passa a comparar com essa migração.
3. Linha nova na matriz de `test_permissions.py` e no [docs/08](docs/08-organizacao-e-permissoes.md#83-catálogo-de-permissões).
