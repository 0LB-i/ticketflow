-- =============================================================================
-- Esboço do schema: itens FORA da v1.0 (decisão de escopo de 2026-10-09)
-- Aplicar sobre esboco-schema.sql quando cada item entrar no roadmap.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Tokens de API (integrações e agentes de IA)
-- -----------------------------------------------------------------------------

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

-- Colunas que voltam junto com os clientes de API
ALTER TABLE audit_log       ADD COLUMN actor_api_client_id bigint REFERENCES api_clients(id);
ALTER TABLE ticket_events   ADD COLUMN actor_api_client_id bigint REFERENCES api_clients(id);
ALTER TABLE ticket_comments ADD COLUMN api_client_id       bigint REFERENCES api_clients(id);
-- Ajustar também os CHECKs: tickets.channel (+ 'api', 'ai_agent'), ticket_comments.source (+ 'api'),
-- ticket_events.actor_kind (+ 'api_client', 'ai') e o CHECK de autor de ticket_comments.

-- -----------------------------------------------------------------------------
-- Webhooks de saída
-- -----------------------------------------------------------------------------

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
-- -----------------------------------------------------------------------------
-- Visões salvas
-- -----------------------------------------------------------------------------

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

-- -----------------------------------------------------------------------------
-- Campos extras por categoria
-- -----------------------------------------------------------------------------

ALTER TABLE categories ADD COLUMN form_schema   jsonb;                          -- JSON Schema dos campos extras
ALTER TABLE tickets    ADD COLUMN custom_fields jsonb NOT NULL DEFAULT '{}';

-- -----------------------------------------------------------------------------
-- Antivírus nos anexos
-- -----------------------------------------------------------------------------

ALTER TABLE attachments
    ADD COLUMN scan_status text NOT NULL DEFAULT 'not_scanned'
        CHECK (scan_status IN ('pending', 'clean', 'infected', 'error', 'not_scanned')),
    ADD COLUMN scanned_at  timestamptz;

-- -----------------------------------------------------------------------------
-- Inteligência artificial  (docs/06, ADR 0004)
-- -----------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS vector;          -- pgvector

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

ALTER TABLE ticket_comments ADD COLUMN ai_run_id bigint REFERENCES ai_runs(id);  -- comentário originado de sugestão de IA

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

ALTER TABLE categories ADD COLUMN ai_allowed boolean NOT NULL DEFAULT true;
