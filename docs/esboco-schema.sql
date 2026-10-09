-- =============================================================================
-- Esboço do schema do Sistema de Chamados
-- Alvo: PostgreSQL 16 e 17 (não usar recursos exclusivos do 17)
-- Status: RASCUNHO para discussão. A versão oficial será gerada via Alembic.
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
-- Identidade e acesso
-- -----------------------------------------------------------------------------

CREATE TABLE users (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id       uuid        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    email           citext      NOT NULL UNIQUE,
    full_name       text        NOT NULL,
    password_hash   text,                               -- NULL quando só usa SSO
    external_id     text,                               -- "sub" do OIDC / objectGUID do AD
    role            text        NOT NULL DEFAULT 'requester'
                    CHECK (role IN ('requester', 'agent', 'supervisor', 'admin')),
    department      text,
    is_active       boolean     NOT NULL DEFAULT true,
    locale          text        NOT NULL DEFAULT 'pt-BR',
    timezone        text        NOT NULL DEFAULT 'America/Sao_Paulo',
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    anonymized_at   timestamptz                         -- LGPD
);

-- Integrações e agentes de IA autenticam como "clientes de API"
CREATE TABLE api_clients (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id       uuid        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    name            text        NOT NULL,
    kind            text        NOT NULL DEFAULT 'integration'
                    CHECK (kind IN ('integration', 'ai_agent')),
    acts_as_user_id bigint      REFERENCES users(id),   -- identidade usada na auditoria
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

-- -----------------------------------------------------------------------------
-- Equipes, categorias e status
-- -----------------------------------------------------------------------------

CREATE TABLE teams (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id       uuid        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    name            text        NOT NULL UNIQUE,
    email_alias     citext      UNIQUE,                 -- ex.: ti@empresa.com abre chamado nesta fila
    is_active       boolean     NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE team_members (
    team_id         bigint      NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id         bigint      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    is_supervisor   boolean     NOT NULL DEFAULT false,
    PRIMARY KEY (team_id, user_id)
);

CREATE TABLE categories (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    parent_id       bigint      REFERENCES categories(id),
    name            text        NOT NULL,
    description     text,                               -- também usada como contexto para a IA classificar
    default_team_id bigint      REFERENCES teams(id),
    form_schema     jsonb,                              -- JSON Schema dos campos personalizados
    ai_allowed      boolean     NOT NULL DEFAULT true,  -- ex.: false para RH/jurídico sensível
    is_active       boolean     NOT NULL DEFAULT true,
    UNIQUE (parent_id, name)
);

CREATE TABLE ticket_statuses (
    id              smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            text        NOT NULL UNIQUE,        -- rótulo exibido
    kind            text        NOT NULL
                    CHECK (kind IN ('new', 'open', 'pending', 'resolved', 'closed', 'canceled')),
    sort_order      smallint    NOT NULL DEFAULT 0,
    is_default      boolean     NOT NULL DEFAULT false
);

-- -----------------------------------------------------------------------------
-- SLA
-- -----------------------------------------------------------------------------

CREATE TABLE business_calendars (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            text        NOT NULL UNIQUE,
    timezone        text        NOT NULL DEFAULT 'America/Sao_Paulo',
    -- ex.: {"mon": [["08:00","12:00"],["13:00","18:00"]], ...}
    working_hours   jsonb       NOT NULL,
    holidays        date[]      NOT NULL DEFAULT '{}'
);

CREATE TABLE sla_policies (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                    text     NOT NULL,
    calendar_id             bigint   NOT NULL REFERENCES business_calendars(id),
    priority                smallint NOT NULL CHECK (priority BETWEEN 1 AND 4),
    category_id             bigint   REFERENCES categories(id),  -- NULL = qualquer categoria
    first_response_minutes  integer  NOT NULL,
    resolution_minutes      integer  NOT NULL,
    UNIQUE NULLS NOT DISTINCT (priority, category_id)            -- PG 15+
);

-- -----------------------------------------------------------------------------
-- Chamados
-- -----------------------------------------------------------------------------

CREATE SEQUENCE ticket_number_seq START WITH 1000;

CREATE TABLE tickets (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id       uuid        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    number          bigint      NOT NULL DEFAULT nextval('ticket_number_seq') UNIQUE,
    title           text        NOT NULL CHECK (length(title) BETWEEN 3 AND 300),
    description     text        NOT NULL DEFAULT '',
    requester_id    bigint      NOT NULL REFERENCES users(id),
    team_id         bigint      REFERENCES teams(id),
    assignee_id     bigint      REFERENCES users(id),
    category_id     bigint      REFERENCES categories(id),
    status_id       smallint    NOT NULL REFERENCES ticket_statuses(id),
    priority        smallint    NOT NULL DEFAULT 2 CHECK (priority BETWEEN 1 AND 4),  -- 1=baixa … 4=crítica
    channel         text        NOT NULL DEFAULT 'web'
                    CHECK (channel IN ('web', 'email', 'api', 'ai_agent', 'chat')),
    custom_fields   jsonb       NOT NULL DEFAULT '{}',
    tags            text[]      NOT NULL DEFAULT '{}',
    satisfaction    smallint    CHECK (satisfaction BETWEEN 1 AND 5),
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
    ai_run_id       bigint,                             -- preenchido se originado de sugestão de IA
    created_at      timestamptz NOT NULL DEFAULT now(),
    edited_at       timestamptz,
    search_vector   tsvector GENERATED ALWAYS AS (to_tsvector('pt_br'::regconfig, body)) STORED,
    CHECK (author_id IS NOT NULL OR api_client_id IS NOT NULL)
);
CREATE INDEX ticket_comments_ticket_idx ON ticket_comments (ticket_id, created_at);
CREATE INDEX ticket_comments_search_idx ON ticket_comments USING gin (search_vector);

CREATE TABLE ticket_attachments (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id       uuid        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    ticket_id       bigint      NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    comment_id      bigint      REFERENCES ticket_comments(id) ON DELETE SET NULL,
    uploaded_by     bigint      REFERENCES users(id),
    filename        text        NOT NULL,
    content_type    text        NOT NULL,
    size_bytes      bigint      NOT NULL,
    storage_key     text        NOT NULL,               -- caminho em disco ou chave S3
    sha256          text        NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ticket_watchers (
    ticket_id       bigint NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    user_id         bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (ticket_id, user_id)
);

CREATE TABLE ticket_links (
    source_id       bigint NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    target_id       bigint NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    kind            text   NOT NULL CHECK (kind IN ('duplicate_of', 'related_to', 'blocked_by')),
    PRIMARY KEY (source_id, target_id, kind),
    CHECK (source_id <> target_id)
);

CREATE TABLE ticket_sla (
    ticket_id               bigint      PRIMARY KEY REFERENCES tickets(id) ON DELETE CASCADE,
    policy_id               bigint      REFERENCES sla_policies(id),
    first_response_due_at   timestamptz,
    resolution_due_at       timestamptz,
    paused_since            timestamptz,            -- preenchido enquanto o status for 'pending'
    paused_minutes_total    integer     NOT NULL DEFAULT 0,
    first_response_breached boolean     NOT NULL DEFAULT false,
    resolution_breached     boolean     NOT NULL DEFAULT false
);
CREATE INDEX ticket_sla_due_idx ON ticket_sla (resolution_due_at)
    WHERE NOT resolution_breached AND paused_since IS NULL;

-- Histórico/auditoria: somente inserção (append-only). Candidata a particionamento mensal.
CREATE TABLE ticket_events (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id       bigint      NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    event_type      text        NOT NULL,           -- ex.: ticket.created, ticket.status_changed
    actor_user_id   bigint      REFERENCES users(id),
    actor_api_client_id bigint  REFERENCES api_clients(id),
    actor_kind      text        NOT NULL CHECK (actor_kind IN ('user', 'api_client', 'ai', 'system')),
    payload         jsonb       NOT NULL DEFAULT '{}',  -- {"field": "status", "from": "...", "to": "..."}
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ticket_events_ticket_idx ON ticket_events (ticket_id, created_at);

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
-- Inteligência artificial
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

-- Log de toda execução de IA: auditoria, custo, qualidade
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
    task            text        NOT NULL,           -- ex.: ai.classify_ticket
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
