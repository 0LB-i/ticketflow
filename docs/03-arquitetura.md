# 3. Arquitetura

## Princípios

1. **API-first.** Toda funcionalidade existe primeiro na API; a interface web e os agentes de IA são clientes dela.
2. **Poucas peças móveis.** O PostgreSQL faz o papel de banco, fila de tarefas, busca textual e busca vetorial. Redis, Elasticsearch etc. só entram se uma medição mostrar que são necessários.
3. **IA é opcional e degradável.** O sistema funciona 100% sem IA. Toda chamada a IA é assíncrona ou tem timeout e fallback.
4. **Monólito modular.** Um único deploy, com módulos de domínio bem separados. Microsserviços só se houver motivo concreto.

## Stack

| Camada | Escolha | Motivo |
|--------|---------|--------|
| Linguagem | Python 3.12+ | Requisito; ecossistema forte em IA |
| Framework web/API | FastAPI | Async, OpenAPI automático, Pydantic |
| Validação / schemas | Pydantic v2 | Integrado ao FastAPI; também usado para saídas estruturadas de IA |
| ORM / SQL | SQLAlchemy 2.x (async) + psycopg 3 | Maduro, tipado, permite SQL explícito quando necessário |
| Migrações | Alembic | Padrão de mercado com SQLAlchemy |
| Banco | PostgreSQL 17 (suporte a 16) | Ver [ADR 0003](adr/0003-postgresql.md) |
| Busca textual | `tsvector` com dicionário `portuguese` + `unaccent` | Nativo, sem serviço extra |
| Busca vetorial | `pgvector` (HNSW) | Nativo, sem serviço extra |
| Fila de tarefas | Tabela no PostgreSQL + `SKIP LOCKED` (avaliar a biblioteca *Procrastinate*) | Sem broker extra; transacional com os dados |
| Cliente HTTP | httpx | Async, usado para webhooks e provedores de IA |
| Autenticação | OIDC (Authlib) + sessão/JWT; senhas com Argon2id | SSO corporativo |
| Interface web | **em aberto**, ver [questões em aberto](questoes-em-aberto.md) | |
| Gerência de pacotes | uv | Rápido, lockfile reprodutível |
| Qualidade | ruff, mypy (ou pyright), pytest, testcontainers | |
| Observabilidade | structlog, OpenTelemetry, prometheus-client | |
| Empacotamento | Docker / Docker Compose; Helm opcional | |

## Visão de componentes

```
                ┌──────────────────────┐   ┌──────────────────────┐
                │  Interface web       │   │ Sistemas externos /  │
                │  (navegador)         │   │ agentes de IA (MCP)  │
                └──────────┬───────────┘   └──────────┬───────────┘
                           │ HTTPS                    │ HTTPS + token
                ┌──────────▼──────────────────────────▼───────────┐
                │                 API (FastAPI)                   │
                │  auth · tickets · teams · sla · kb · ai · admin │
                └──────────┬──────────────────────────┬───────────┘
                           │                          │ enfileira tarefas
                ┌──────────▼───────────┐   ┌──────────▼───────────┐
                │     PostgreSQL       │◄──┤      Worker(s)       │
                │ dados · fila · FTS · │   │ e-mail · webhooks ·  │
                │ pgvector · auditoria │   │ SLA · IA · embeddings│
                └──────────────────────┘   └──────────┬───────────┘
                                                      │
                                ┌─────────────────────┼─────────────────────┐
                                ▼                     ▼                     ▼
                         Provedores de IA      Servidor SMTP/IMAP    Webhooks de saída
                       (Claude, OpenAI, local)
```

**Processos:**

- `api`: servidor ASGI (uvicorn), sem estado, escala horizontalmente
- `worker`: consome a fila de tarefas (envio de e-mail, webhooks, cálculo de SLA, chamadas de IA, geração de embeddings)
- `scheduler`: tarefas periódicas (verificação de SLA, fechamento automático, leitura da caixa de e-mail). Pode rodar dentro do worker com lock (`pg_try_advisory_lock`) para garantir uma única instância ativa

## Estrutura de código proposta

```
src/chamados/
├── main.py                  # cria a app FastAPI
├── config.py                # settings (pydantic-settings, variáveis de ambiente)
├── db/                      # engine, sessão, base declarativa
├── core/                    # segurança, permissões, erros, paginação, eventos
├── modules/
│   ├── identity/            # usuários, papéis, autenticação, tokens de API
│   ├── teams/               # equipes e membros
│   ├── tickets/             # chamados, comentários, anexos, status, histórico
│   ├── sla/                 # políticas, calendários, cálculo
│   ├── knowledge/           # base de conhecimento
│   ├── notifications/       # e-mail, preferências
│   ├── webhooks/            # assinaturas e entregas
│   ├── ai/                  # provedores, prompts, execuções, embeddings
│   └── reports/
│       # cada módulo: models.py · schemas.py · service.py · repository.py · router.py
├── worker/                  # fila de tarefas e handlers
└── mcp/                     # servidor MCP (fase 4)
migrations/                  # Alembic
tests/
```

Regra de dependência: `router → service → repository → models`. Os módulos se comunicam pelos **services** e por **eventos de domínio** (ex.: `ticket.created`), nunca acessando diretamente os repositórios de outro módulo.

## Eventos de domínio

Toda mudança relevante gera um evento gravado **na mesma transação** em `ticket_events` (histórico/auditoria) e em `outbox` (padrão *transactional outbox*). O worker lê o outbox e dispara:

- notificações por e-mail
- webhooks de saída
- tarefas de IA (classificar, gerar embedding, resumir)
- recálculo de SLA

Assim nenhuma notificação é enviada para uma transação que deu rollback, e nenhum evento se perde se o processo cair.

## Segurança

- RBAC no nível de serviço (não só na rota) e filtros de visibilidade aplicados nas consultas
- Opcionalmente, Row-Level Security do PostgreSQL como segunda camada (avaliar na Fase 2)
- Anexos: limite de tamanho, verificação de tipo MIME, antivírus opcional (ClamAV), armazenamento em disco ou S3-compatível, download por URL assinada
- Rate limiting por usuário e por token de API
- Segredos (chaves de provedores de IA, SMTP) criptografados em repouso ou fornecidos via variáveis de ambiente / gerenciador de segredos

## Implantação

- **Desenvolvimento:** `docker compose` (PostgreSQL 17 + pgvector, Mailpit para capturar e-mails)
- **Produção mínima:** 1 VM com Docker: `api` + `worker` + PostgreSQL gerenciado ou local com backup (pgBackRest ou `pg_dump` agendado)
- **Produção escalável:** Kubernetes com `api` e `worker` em réplicas e PostgreSQL gerenciado
