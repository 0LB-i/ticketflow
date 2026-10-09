-- =============================================================================
-- Esboço do schema do Sistema de Chamados
-- Alvo: PostgreSQL 16 e 17 (não usar recursos exclusivos do 17)
-- Modelo: uma instalação por empresa (sem tenant_id) — ADR 0005
-- Sem SLA (decisão 2026-10-09): não há calendários, políticas nem prazos.
-- Status: RASCUNHO para discussão. A versão oficial será gerada via Alembic.
-- Documentos de referência: docs/08 (permissões), 09 (login), 10 (chamados), 11 (anexos)
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;          -- pgvector

-- Configuração de busca textual: português + remoção de acentos.
-- Com regconfig explícito, to_tsvector é IMMUTABLE e pode ser usado em coluna gerada.
CREATE TEXT SEARCH CONFIGURATION pt_br (COPY = portuguese);
ALTER TEXT SEARCH CONFIGURATION pt_br
    ALTER MAPPING FOR hword, hword_part, word WITH unaccent, portuguese_stem;

-- -----------------------------------------------------------------------------
-- Configurações gerais (chave/valor), ex.: matriz de prioridade, prazos de
-- fechamento automático, tipos de arquivo permitidos, configuração de SSO
-- -----------------------------------------------------------------------------

CREATE TABLE settings (
    key             text        PRIMARY KEY,
    value           jsonb       NOT NULL,
    updated_by      bigint,                             -- FK adicionada após users
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Organização: setores e papéis  (docs/08)
-- -----------------------------------------------------------------------------

CREATE TABLE departments (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id       uuid        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    parent_id       bigint      REFERENCES departments(id),
    name            text        NOT NULL,
    code            text        UNIQUE,                 -- código / centro de custo; usado no mapeamento do SSO
    is_active       boolean     NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (parent_id, name)
);

-- Papéis globais. Os papéis do sistema (requester, agent, admin, auditor) vêm de seed
-- e não podem ser alterados; papéis personalizados chegam na Fase 2.
CREATE TABLE roles (
    id              smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code            text        NOT NULL UNIQUE,        -- requester, agent, admin, auditor, ...
    name            text        NOT NULL,
    permissions     text[]      NOT NULL,               -- códigos do catálogo (core/permissions.py)
    is_system       boolean     NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Usuários e autenticação  (docs/09)
-- -----------------------------------------------------------------------------

CREATE TABLE users (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id       uuid        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    email           citext      NOT NULL UNIQUE,
    full_name       text        NOT NULL,
    role_id         smallint    NOT NULL REFERENCES roles(id),
    department_id   bigint      NOT NULL REFERENCES departments(id),
    job_title       text,
    phone           text,
    password_hash   text,                               -- NULL quando só usa SSO
    password_changed_at timestamptz,
    local_login_allowed boolean NOT NULL DEFAULT true,  -- exceção quando "SSO obrigatório" está ligado
    external_id     text        UNIQUE,                 -- "sub" do OIDC
    is_active       boolean     NOT NULL DEFAULT true,
    failed_logins   smallint    NOT NULL DEFAULT 0,
    locked_until    timestamptz,
    locale          text        NOT NULL DEFAULT 'pt-BR',
    timezone        text        NOT NULL DEFAULT 'America/Sao_Paulo',
    avatar_key      text,                               -- chave no armazenamento
    notification_prefs jsonb    NOT NULL DEFAULT '{}',
    last_login_at   timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    anonymized_at   timestamptz                         -- LGPD
);
CREATE INDEX users_department_idx ON users (department_id) WHERE is_active;
CREATE INDEX users_name_trgm_idx  ON users USING gin (full_name gin_trgm_ops);  -- autocompletar

ALTER TABLE settings
    ADD CONSTRAINT settings_updated_by_fk FOREIGN KEY (updated_by) REFERENCES users(id);

CREATE TABLE department_managers (
    department_id   bigint      NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    user_id         bigint      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source          text        NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'idp', 'import')),
    PRIMARY KEY (department_id, user_id)
);

-- Sessões no servidor; o cookie carrega só um identificador aleatório
CREATE TABLE user_sessions (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         bigint      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      text        NOT NULL UNIQUE,        -- SHA-256 do identificador do cookie
    csrf_token_hash text        NOT NULL,
    mfa_verified    boolean     NOT NULL DEFAULT false,
    auth_method     text        NOT NULL CHECK (auth_method IN ('password', 'oidc')),
    ip              inet,
    user_agent      text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_seen_at    timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,               -- limite absoluto (ex.: 7 dias)
    revoked_at      timestamptz
);
CREATE INDEX user_sessions_user_idx ON user_sessions (user_id) WHERE revoked_at IS NULL;

-- Tokens de uso único: convite e redefinição de senha
CREATE TABLE auth_tokens (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         bigint      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose         text        NOT NULL CHECK (purpose IN ('invite', 'password_reset')),
    token_hash      text        NOT NULL UNIQUE,
    expires_at      timestamptz NOT NULL,
    used_at         timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE user_mfa (
    user_id         bigint      PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    totp_secret_enc bytea       NOT NULL,               -- criptografado com a chave da aplicação
    recovery_codes  text[]      NOT NULL,               -- hashes dos códigos de recuperação
    enabled_at      timestamptz NOT NULL DEFAULT now(),
    last_used_step  bigint                              -- evita reutilizar o mesmo código TOTP
);

-- Integrações e agentes de IA autenticam como "clientes de API"
CREATE TABLE api_clients (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id       uuid        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    name            text        NOT NULL,
    kind            text        NOT NULL DEFAULT 'integration'
                    CHECK (kind IN ('integration', 'ai_agent')),
    acts_as_user_id bigint      NOT NULL REFERENCES users(id),  -- conta de serviço usada nas permissões
    is_active       boolean     NOT NULL DEFAULT true,
    created_by      bigint      NOT NULL REFERENCES users(id),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE api_tokens (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    api_client_id   bigint      NOT NULL REFERENCES api_clients(id) ON DELETE CASCADE,
    token_prefix    text        NOT NULL,               -- primeiros caracteres, para identificar
    token_hash      text        NOT NULL UNIQUE,        -- SHA-256 do token; o token nunca é armazenado
    scopes          text[]      NOT NULL,               -- ex.: {tickets:read, tickets:write, kb:read}
    expires_at      timestamptz,
    last_used_at    timestamptz,
    revoked_at      timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Auditoria de tudo que não é histórico de chamado: login, administração, permissões
CREATE TABLE audit_log (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    action          text        NOT NULL,               -- ex.: auth.login_failed, user.role_changed
    actor_user_id   bigint      REFERENCES users(id),
    actor_api_client_id bigint  REFERENCES api_clients(id),
    target_type     text,                               -- ex.: user, team, setting
    target_id       text,
    ip              inet,
    user_agent      text,
    before          jsonb,
    after           jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_created_idx ON audit_log (created_at);
CREATE INDEX audit_log_target_idx  ON audit_log (target_type, target_id);

-- -----------------------------------------------------------------------------
-- Grupos de atendimento  (docs/08)
-- -----------------------------------------------------------------------------

CREATE TABLE teams (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id       uuid        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    name            text        NOT NULL UNIQUE,
    description     text,
    email_alias     citext      UNIQUE,                 -- ex.: ti@empresa.com abre chamado nesta fila
    notify_on_new   text        NOT NULL DEFAULT 'queue_only'
                    CHECK (notify_on_new IN ('queue_only', 'email_all_members')),
    is_active       boolean     NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE team_members (
    team_id         bigint      NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id         bigint      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role            text        NOT NULL DEFAULT 'member' CHECK (role IN ('member', 'supervisor')),
    source          text        NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'idp', 'import')),
    added_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, user_id)
);
CREATE INDEX team_members_user_idx ON team_members (user_id);

-- Mapeamento de grupos do provedor de identidade (SSO) → papel, grupo ou setor  (docs/09 §9.6)
CREATE TABLE idp_group_mappings (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    idp_group       text        NOT NULL,               -- id ou nome do grupo no provedor
    role_id         smallint    REFERENCES roles(id),
    team_id         bigint      REFERENCES teams(id),
    team_role       text        CHECK (team_role IN ('member', 'supervisor')),
    department_id   bigint      REFERENCES departments(id),
    CHECK (num_nonnulls(role_id, team_id, department_id) = 1),
    CHECK ((team_id IS NULL) = (team_role IS NULL))
);

-- -----------------------------------------------------------------------------
-- Catálogo: categorias, status, códigos de resolução  (docs/10)
-- -----------------------------------------------------------------------------

CREATE TABLE categories (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id       uuid        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    parent_id       bigint      REFERENCES categories(id),
    name            text        NOT NULL,
    description     text,                               -- exibida no catálogo e usada como contexto pela IA
    icon            text,
    default_team_id bigint      REFERENCES teams(id),
    default_type    text        NOT NULL DEFAULT 'incident'
                    CHECK (default_type IN ('incident', 'request', 'question')),
    form_schema     jsonb,                              -- JSON Schema dos campos extras
    requires_approval boolean   NOT NULL DEFAULT false,
    approver_kind   text        CHECK (approver_kind IN ('department_manager', 'user', 'team')),
    approver_user_id bigint     REFERENCES users(id),
    approver_team_id bigint     REFERENCES teams(id),
    is_confidential boolean     NOT NULL DEFAULT false, -- restringe a visibilidade (docs/08 §8.4)
    ai_allowed      boolean     NOT NULL DEFAULT true,
    sort_order      smallint    NOT NULL DEFAULT 0,
    is_active       boolean     NOT NULL DEFAULT true,
    UNIQUE (parent_id, name),
    CHECK (NOT requires_approval OR approver_kind IS NOT NULL),
    CHECK (approver_kind IS DISTINCT FROM 'user' OR approver_user_id IS NOT NULL),
    CHECK (approver_kind IS DISTINCT FROM 'team' OR approver_team_id IS NOT NULL)
);

CREATE TABLE ticket_statuses (
    id              smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            text        NOT NULL UNIQUE,        -- rótulo exibido (renomeável)
    requester_label text,                               -- texto amigável para o solicitante
    kind            text        NOT NULL
                    CHECK (kind IN ('approval', 'open', 'waiting', 'resolved', 'closed', 'canceled')),
    sort_order      smallint    NOT NULL DEFAULT 0,
    is_default_for_kind boolean NOT NULL DEFAULT false
);

CREATE TABLE resolution_codes (
    id              smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            text        NOT NULL UNIQUE,        -- Resolvido, Contorno, Não reproduzível, ...
    is_active       boolean     NOT NULL DEFAULT true
);

-- -----------------------------------------------------------------------------
-- Chamados  (docs/10)
-- -----------------------------------------------------------------------------

CREATE SEQUENCE ticket_number_seq START WITH 1000;

CREATE TABLE tickets (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id       uuid        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    number          bigint      NOT NULL DEFAULT nextval('ticket_number_seq') UNIQUE,
    title           text        NOT NULL CHECK (length(title) BETWEEN 3 AND 300),
    description     text        NOT NULL DEFAULT '',
    type            text        NOT NULL CHECK (type IN ('incident', 'request', 'question')),
    requester_id    bigint      NOT NULL REFERENCES users(id),
    opened_by_id    bigint      NOT NULL REFERENCES users(id),        -- = requester_id quando o próprio abriu
    department_id   bigint      NOT NULL REFERENCES departments(id),  -- setor do solicitante NA ABERTURA
    team_id         bigint      REFERENCES teams(id),
    assignee_id     bigint      REFERENCES users(id),
    category_id     bigint      REFERENCES categories(id),
    status_id       smallint    NOT NULL REFERENCES ticket_statuses(id),
    impact          smallint    NOT NULL DEFAULT 1 CHECK (impact BETWEEN 1 AND 3),   -- 1=individual 2=setor 3=empresa
    urgency         smallint    NOT NULL DEFAULT 1 CHECK (urgency BETWEEN 1 AND 3),  -- 1=pode esperar 3=parado
    priority        smallint    NOT NULL CHECK (priority BETWEEN 1 AND 4),           -- 1=baixa … 4=crítica
    priority_overridden boolean NOT NULL DEFAULT false,
    channel         text        NOT NULL DEFAULT 'portal'
                    CHECK (channel IN ('portal', 'email', 'phone', 'walk_in', 'api', 'ai_agent')),
    custom_fields   jsonb       NOT NULL DEFAULT '{}',
    tags            text[]      NOT NULL DEFAULT '{}',
    resolution_code_id smallint REFERENCES resolution_codes(id),
    reopened_count  smallint    NOT NULL DEFAULT 0,
    satisfaction    smallint    CHECK (satisfaction BETWEEN 1 AND 5),
    satisfaction_comment text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    first_response_at timestamptz,
    resolved_at     timestamptz,
    closed_at       timestamptz,
    deleted_at      timestamptz,
    search_vector   tsvector GENERATED ALWAYS AS (
                        setweight(to_tsvector('pt_br'::regconfig, coalesce(title, '')), 'A') ||
                        setweight(to_tsvector('pt_br'::regconfig, coalesce(description, '')), 'B')
                    ) STORED
);

CREATE INDEX tickets_search_idx      ON tickets USING gin (search_vector);
CREATE INDEX tickets_title_trgm_idx  ON tickets USING gin (title gin_trgm_ops);
CREATE INDEX tickets_tags_idx        ON tickets USING gin (tags);
CREATE INDEX tickets_queue_idx       ON tickets (team_id, status_id, priority DESC, created_at)
                                     WHERE deleted_at IS NULL;
CREATE INDEX tickets_assignee_idx    ON tickets (assignee_id, status_id) WHERE deleted_at IS NULL;
CREATE INDEX tickets_requester_idx   ON tickets (requester_id, created_at DESC);
CREATE INDEX tickets_department_idx  ON tickets (department_id, created_at DESC);

-- Grupos que já atenderam o chamado (regra 6 de visibilidade); mantida a cada transferência
CREATE TABLE ticket_teams (
    ticket_id       bigint      NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    team_id         bigint      NOT NULL REFERENCES teams(id),
    first_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ticket_id, team_id)
);
CREATE INDEX ticket_teams_team_idx ON ticket_teams (team_id);

CREATE TABLE ticket_comments (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id       uuid        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    ticket_id       bigint      NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    author_id       bigint      REFERENCES users(id),
    api_client_id   bigint      REFERENCES api_clients(id),
    visibility      text        NOT NULL DEFAULT 'public'
                    CHECK (visibility IN ('public', 'internal')),
    body            text        NOT NULL,
    body_format     text        NOT NULL DEFAULT 'markdown',
    is_solution     boolean     NOT NULL DEFAULT false, -- texto da solução ao resolver
    source          text        NOT NULL DEFAULT 'web'
                    CHECK (source IN ('web', 'email', 'api', 'system')),
    ai_run_id       bigint,                             -- preenchido se originado de sugestão de IA
    created_at      timestamptz NOT NULL DEFAULT now(),
    edited_at       timestamptz,                        -- versões anteriores ficam em ticket_events
    hidden_at       timestamptz,
    hidden_by       bigint      REFERENCES users(id),
    hidden_reason   text,
    search_vector   tsvector GENERATED ALWAYS AS (to_tsvector('pt_br'::regconfig, body)) STORED,
    CHECK (author_id IS NOT NULL OR api_client_id IS NOT NULL OR source = 'system'),
    CHECK ((hidden_at IS NULL) = (hidden_reason IS NULL))
);
CREATE INDEX ticket_comments_ticket_idx ON ticket_comments (ticket_id, created_at);
CREATE INDEX ticket_comments_search_idx ON ticket_comments USING gin (search_vector);

CREATE TABLE ticket_watchers (
    ticket_id       bigint      NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    user_id         bigint      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind            text        NOT NULL DEFAULT 'watcher'
                    CHECK (kind IN ('watcher', 'mentioned')),   -- 'mentioned' vê notas internas
    added_by        bigint      REFERENCES users(id),
    added_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ticket_id, user_id)
);
CREATE INDEX ticket_watchers_user_idx ON ticket_watchers (user_id);

CREATE TABLE ticket_links (
    source_id       bigint NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    target_id       bigint NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    kind            text   NOT NULL CHECK (kind IN ('duplicate_of', 'related_to', 'blocked_by')),
    created_by      bigint REFERENCES users(id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, target_id, kind),
    CHECK (source_id <> target_id)
);

-- Aprovações  (docs/10 §10.8)
CREATE TABLE ticket_approvals (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id       bigint      NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    approver_kind   text        NOT NULL CHECK (approver_kind IN ('department_manager', 'user', 'team')),
    approver_user_id bigint     REFERENCES users(id),
    approver_team_id bigint     REFERENCES teams(id),
    approver_department_id bigint REFERENCES departments(id),  -- quando o aprovador é o gestor do setor
    status          text        NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected', 'redirected', 'canceled')),
    decided_by      bigint      REFERENCES users(id),
    decided_at      timestamptz,
    comment         text,
    reminders_sent  smallint    NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (status <> 'rejected' OR comment IS NOT NULL)        -- reprovação exige motivo
);
CREATE INDEX ticket_approvals_pending_idx ON ticket_approvals (ticket_id) WHERE status = 'pending';

-- Histórico do chamado: somente inserção (append-only). Candidata a particionamento mensal.
CREATE TABLE ticket_events (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id       bigint      NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    event_type      text        NOT NULL,           -- ex.: ticket.created, ticket.status_changed, ticket.transferred
    actor_user_id   bigint      REFERENCES users(id),
    actor_api_client_id bigint  REFERENCES api_clients(id),
    actor_kind      text        NOT NULL CHECK (actor_kind IN ('user', 'api_client', 'ai', 'system')),
    payload         jsonb       NOT NULL DEFAULT '{}',  -- {"field": "status", "from": "...", "to": "...", "reason": "..."}
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ticket_events_ticket_idx ON ticket_events (ticket_id, created_at);

-- Respostas prontas (macros)  (docs/10 §10.6)
CREATE TABLE canned_responses (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scope           text        NOT NULL CHECK (scope IN ('personal', 'team', 'global')),
    owner_user_id   bigint      REFERENCES users(id) ON DELETE CASCADE,
    team_id         bigint      REFERENCES teams(id) ON DELETE CASCADE,
    title           text        NOT NULL,
    body            text        NOT NULL,           -- com variáveis {{solicitante.nome}} etc.
    actions         jsonb       NOT NULL DEFAULT '[]',  -- ex.: [{"set_status": "pending"}, {"add_tag": "vpn"}]
    created_by      bigint      NOT NULL REFERENCES users(id),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (scope <> 'personal' OR owner_user_id IS NOT NULL),
    CHECK (scope <> 'team' OR team_id IS NOT NULL)
);

-- Visões salvas (filtros)  (Fase 2)
CREATE TABLE saved_views (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            text        NOT NULL,
    owner_user_id   bigint      REFERENCES users(id) ON DELETE CASCADE,  -- visão pessoal
    team_id         bigint      REFERENCES teams(id) ON DELETE CASCADE,  -- visão compartilhada do grupo
    filters         jsonb       NOT NULL,
    sort            text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(owner_user_id, team_id) = 1)
);

-- Notificações dentro do sistema (sino)  (Fase 2)
CREATE TABLE notifications (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         bigint      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticket_id       bigint      REFERENCES tickets(id) ON DELETE CASCADE,
    event_type      text        NOT NULL,
    payload         jsonb       NOT NULL DEFAULT '{}',
    read_at         timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX notifications_unread_idx ON notifications (user_id, created_at DESC) WHERE read_at IS NULL;

-- -----------------------------------------------------------------------------
-- Base de conhecimento
-- -----------------------------------------------------------------------------

CREATE TABLE kb_articles (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id       uuid        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    title           text        NOT NULL,
    body            text        NOT NULL,
    category_id     bigint      REFERENCES categories(id),
    audience        text        NOT NULL DEFAULT 'internal'
                    CHECK (audience IN ('internal', 'everyone')),  -- 'internal' = só agentes
    status          text        NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'published', 'archived')),
    source_ticket_id bigint     REFERENCES tickets(id),             -- gerado a partir de um chamado
    author_id       bigint      REFERENCES users(id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    search_vector   tsvector GENERATED ALWAYS AS (
                        setweight(to_tsvector('pt_br'::regconfig, title), 'A') ||
                        setweight(to_tsvector('pt_br'::regconfig, body), 'B')
                    ) STORED
);
CREATE INDEX kb_articles_search_idx ON kb_articles USING gin (search_vector);

-- -----------------------------------------------------------------------------
-- Anexos  (docs/11)
-- Dono: chamado (+ comentário opcional) OU artigo. Todos nulos = upload temporário.
-- -----------------------------------------------------------------------------

CREATE TABLE attachments (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id       uuid        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    ticket_id       bigint      REFERENCES tickets(id) ON DELETE CASCADE,
    comment_id      bigint      REFERENCES ticket_comments(id) ON DELETE CASCADE,
    kb_article_id   bigint      REFERENCES kb_articles(id) ON DELETE CASCADE,
    visibility      text        CHECK (visibility IN ('public', 'internal')),  -- definida ao vincular
    filename        text        NOT NULL,           -- nome original saneado
    content_type    text        NOT NULL,           -- detectado pelo conteúdo, não pelo navegador
    size_bytes      bigint      NOT NULL CHECK (size_bytes > 0),
    sha256          text        NOT NULL,
    storage_backend text        NOT NULL CHECK (storage_backend IN ('local', 's3')),
    storage_key     text        NOT NULL UNIQUE,    -- attachments/AAAA/MM/<uuid>
    scan_status     text        NOT NULL DEFAULT 'pending'
                    CHECK (scan_status IN ('pending', 'clean', 'infected', 'error', 'not_scanned')),
    scanned_at      timestamptz,
    uploaded_by     bigint      NOT NULL REFERENCES users(id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    linked_at       timestamptz,
    hidden_at       timestamptz,
    hidden_by       bigint      REFERENCES users(id),
    hidden_reason   text,
    CHECK (num_nonnulls(ticket_id, kb_article_id) <= 1),
    CHECK (comment_id IS NULL OR ticket_id IS NOT NULL),
    CHECK ((linked_at IS NULL) = (ticket_id IS NULL AND kb_article_id IS NULL)),
    CHECK (linked_at IS NULL OR visibility IS NOT NULL)
);
CREATE INDEX attachments_ticket_idx   ON attachments (ticket_id) WHERE ticket_id IS NOT NULL;
CREATE INDEX attachments_comment_idx  ON attachments (comment_id) WHERE comment_id IS NOT NULL;
CREATE INDEX attachments_orphans_idx  ON attachments (created_at) WHERE linked_at IS NULL;

-- -----------------------------------------------------------------------------
-- Inteligência artificial  (docs/06, ADR 0004)
-- -----------------------------------------------------------------------------

-- Endpoints de IA: API genérica no formato compatível com OpenAI.
-- Não existe código por provedor; o modelo é só um texto repassado à API.
-- (a chave de API fica fora do banco: variável de ambiente ou gerenciador de segredos)
CREATE TABLE ai_endpoints (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            text        NOT NULL UNIQUE,    -- ex.: "principal", "local-sensivel", "embeddings"
    base_url        text        NOT NULL,           -- ex.: https://ia.empresa.local/v1
    secret_ref      text,                           -- nome da variável de ambiente / segredo (NULL = sem auth)
    model           text        NOT NULL,           -- texto livre, enviado no campo "model" da requisição
    -- ex.: {"timeout_s": 30, "temperature": 0.2, "max_tokens": 1024,
    --       "json_schema_mode": false, "extra_headers": {}}
    settings        jsonb       NOT NULL DEFAULT '{}',
    is_active       boolean     NOT NULL DEFAULT true
);

-- Qual endpoint atende cada funcionalidade
CREATE TABLE ai_features (
    feature         text        PRIMARY KEY,        -- classify, summarize, suggest_reply, embed, ...
    endpoint_id     bigint      REFERENCES ai_endpoints(id),
    prompt_version  text,
    is_enabled      boolean     NOT NULL DEFAULT false,
    auto_apply      boolean     NOT NULL DEFAULT false,  -- false = só sugere, um humano confirma
    min_confidence  numeric(3,2)
);

-- Log de toda execução de IA: auditoria, consumo, qualidade
CREATE TABLE ai_runs (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    feature         text        NOT NULL,
    ticket_id       bigint      REFERENCES tickets(id) ON DELETE SET NULL,
    endpoint_id     bigint      REFERENCES ai_endpoints(id),
    model           text        NOT NULL,           -- cópia do modelo usado na época (o endpoint pode mudar)
    prompt_version  text,
    input_redacted  jsonb,                          -- entrada JÁ mascarada (sem dados pessoais)
    output          jsonb,
    status          text        NOT NULL CHECK (status IN ('pending', 'ok', 'error', 'timeout')),
    error           text,
    input_tokens    integer,
    output_tokens   integer,
    latency_ms      integer,
    feedback        text        CHECK (feedback IN ('accepted', 'edited', 'rejected')),
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ai_runs_ticket_idx ON ai_runs (ticket_id, created_at);

ALTER TABLE ticket_comments
    ADD CONSTRAINT ticket_comments_ai_run_fk FOREIGN KEY (ai_run_id) REFERENCES ai_runs(id);

-- Embeddings para busca semântica e detecção de duplicados.
-- A dimensão depende do modelo de embeddings configurado: definida na instalação
-- (AI_EMBEDDING_DIM) e aplicada pela migração. Trocar de modelo exige reindexar.
CREATE TABLE embeddings (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_type     text        NOT NULL CHECK (source_type IN ('ticket', 'comment', 'kb_article')),
    source_id       bigint      NOT NULL,
    chunk_index     smallint    NOT NULL DEFAULT 0,
    content_hash    text        NOT NULL,           -- evita recalcular sem mudança
    model           text        NOT NULL,
    embedding       vector(1024) NOT NULL,          -- 1024 = AI_EMBEDDING_DIM (exemplo)
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_type, source_id, chunk_index, model)
);
CREATE INDEX embeddings_hnsw_idx ON embeddings USING hnsw (embedding vector_cosine_ops);

-- -----------------------------------------------------------------------------
-- Integração: outbox, fila de tarefas, webhooks
-- -----------------------------------------------------------------------------

-- Transactional outbox: gravado na mesma transação da mudança de domínio
CREATE TABLE outbox (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type      text        NOT NULL,
    payload         jsonb       NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    processed_at    timestamptz
);
CREATE INDEX outbox_pending_idx ON outbox (id) WHERE processed_at IS NULL;

-- Fila de tarefas (consumida com SELECT ... FOR UPDATE SKIP LOCKED)
CREATE TABLE jobs (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    queue           text        NOT NULL DEFAULT 'default',
    task            text        NOT NULL,           -- ex.: ai.classify_ticket, attachments.scan
    args            jsonb       NOT NULL DEFAULT '{}',
    status          text        NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'running', 'done', 'failed')),
    attempts        smallint    NOT NULL DEFAULT 0,
    max_attempts    smallint    NOT NULL DEFAULT 5,
    run_after       timestamptz NOT NULL DEFAULT now(),
    last_error      text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz
);
CREATE INDEX jobs_ready_idx ON jobs (queue, run_after) WHERE status = 'queued';

CREATE TABLE webhook_subscriptions (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id       uuid        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    url             text        NOT NULL,
    secret          text        NOT NULL,           -- para a assinatura HMAC-SHA256
    event_types     text[]      NOT NULL,           -- ex.: {ticket.created, ticket.comment_added}
    is_active       boolean     NOT NULL DEFAULT true,
    created_by      bigint      REFERENCES users(id),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE webhook_deliveries (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subscription_id bigint      NOT NULL REFERENCES webhook_subscriptions(id) ON DELETE CASCADE,
    event_id        uuid        NOT NULL,           -- idempotência do lado do receptor
    event_type      text        NOT NULL,
    payload         jsonb       NOT NULL,
    response_status smallint,
    attempts        smallint    NOT NULL DEFAULT 0,
    delivered_at    timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);
