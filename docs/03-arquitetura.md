# 3. Arquitetura

## Princípios

1. **API-first.** Toda funcionalidade existe primeiro na API REST. A interface web (SPA em Vue) é só mais um cliente dela. Tudo o que a tela faz também pode ser feito pela API, o que deixa o caminho pronto para integrações e agentes de IA depois da v1.0.
2. **Poucas peças móveis.** O PostgreSQL faz o papel de banco, fila de tarefas e busca textual (e, quando a IA entrar, busca vetorial). Redis, Elasticsearch etc. só entram se uma medição mostrar que são necessários.
3. **IA é opcional e degradável.** A v1.0 não tem IA. Quando ela entrar, o sistema continua funcionando 100% sem ela: toda chamada a IA é assíncrona ou tem timeout e fallback.
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
| Busca vetorial (futuro) | `pgvector` (HNSW) | Nativo, sem serviço extra. Entra com a IA |
| Fila de tarefas | Tabela no PostgreSQL + `SKIP LOCKED` (avaliar a biblioteca *Procrastinate*) | Sem broker extra; transacional com os dados |
| Cliente HTTP | httpx | Async; usado no futuro para webhooks e para a API de IA |
| Autenticação | E-mail e senha (Argon2id) + sessão no servidor; TOTP para MFA | A Martiniti não tem diretório de contas; SSO fica para o futuro |
| Interface web | Vue 3 + TypeScript + Vite + Tailwind CSS, Vue Router, Pinia, TanStack Query | SPA consumindo a API. Ver [ADR 0007](adr/0007-interface-web-vue.md) |
| Cliente da API no frontend | Tipos gerados do OpenAPI (`openapi-typescript` + `openapi-fetch`) | O contrato do backend vira tipos TypeScript; mudança incompatível quebra o build |
| IA (futuro) | Cliente HTTP genérico no formato compatível com OpenAI | Sem acoplamento a provedor ou modelo. Ver [ADR 0004](adr/0004-ia-api-generica-e-assistiva.md) |
| Gerência de pacotes | uv | Rápido, lockfile reprodutível |
| Qualidade (backend) | ruff, mypy (ou pyright), pytest, testcontainers | |
| Qualidade (frontend) | ESLint, Prettier, vue-tsc, Vitest, Playwright (testes ponta a ponta) | |
| Observabilidade | structlog, OpenTelemetry, prometheus-client | |
| Execução | systemd + uvicorn atrás do nginx; Docker Compose só em desenvolvimento | Ver [ADR 0010](adr/0010-producao-systemd.md) |

## Visão de componentes

```
                ┌──────────────────────┐
                │  Interface web       │
                │  (navegador)         │
                └──────────┬───────────┘
                           │ HTTPS
                ┌──────────▼──────────────────────────────────────┐
                │                 API (FastAPI)                   │
                │  auth · tickets · teams · kb · admin            │
                └──────────┬──────────────────────────┬───────────┘
                           │                          │ enfileira tarefas
                ┌──────────▼───────────┐   ┌──────────▼───────────┐
                │     PostgreSQL       │◄──┤      Worker          │
                │ dados · fila · FTS · │   │ e-mail · rotinas     │
                │ auditoria            │   │                      │
                └──────────────────────┘   └──────────┬───────────┘
                                                      ▼
                                                Servidor SMTP
```

Depois da v1.0 entram, sem mudar essa estrutura: sistemas externos e agentes de IA chamando a API com token (e via MCP), o worker chamando a API de IA genérica e enviando webhooks de saída, e o `pgvector` no PostgreSQL. Ver [Integração com IA](06-integracao-ia.md).

**Processos:**

- `api`: servidor ASGI (uvicorn), sem estado, escala horizontalmente
- `worker`: consome a fila de tarefas (envio de e-mail; no futuro, webhooks e chamadas de IA)
- `scheduler`: tarefas periódicas (lembretes de aprovação, limpeza de uploads). Pode rodar dentro do worker com lock (`pg_try_advisory_lock`) para garantir uma única instância ativa

## Estrutura de código proposta

Monorepo com o backend e o frontend no mesmo repositório, versionados juntos:

```
backend/
├── pyproject.toml
├── migrations/              # Alembic
├── tests/
└── src/chamados/
    ├── main.py                  # cria a app FastAPI
    ├── config.py                # settings (pydantic-settings, variáveis de ambiente)
    ├── db/                      # engine, sessão, base declarativa
    ├── core/                    # permissões (catálogo, can(), filtro de visibilidade), erros, paginação, eventos
    ├── modules/
    │   ├── identity/            # usuários, sessões, login, MFA
    │   ├── organization/        # grupos, setores atendidos, papéis
    │   ├── catalog/             # categorias, status, códigos de resolução
    │   ├── tickets/             # chamados, comentários, transições, histórico, aprovações
    │   ├── attachments/         # upload, armazenamento
    │   ├── audit/               # audit_log
    │   ├── knowledge/           # base de conhecimento
    │   ├── notifications/       # e-mail, notificações no sistema, preferências
    │   └── reports/
    │       # cada módulo: models.py · schemas.py · service.py · repository.py · router.py
    └── worker/                  # fila de tarefas e handlers

frontend/
├── package.json             # pnpm
├── vite.config.ts           # em dev, proxy de /api para o backend
└── src/
    ├── main.ts
    ├── api/                 # cliente tipado gerado do OpenAPI
    ├── router/              # rotas e guardas por papel (agente, admin, auditor)
    ├── stores/              # Pinia: sessão, preferências
    ├── views/               # páginas: tickets/, reports/, admin/
    ├── components/          # componentes reutilizáveis (base acessível + Tailwind)
    ├── composables/         # lógica reutilizável (useTickets, usePermissions…)
    ├── i18n/                # vue-i18n, pt-BR
    └── assets/main.css      # entrada do Tailwind
```

Depois da v1.0, os módulos `webhooks/` e `ai/` e o servidor `mcp/` entram nessa mesma estrutura.

O backend não conhece o frontend: só expõe a API. O frontend nunca contém regra de negócio além de validação de formulário para dar retorno rápido; a validação que vale é a da API.

Regra de dependência no backend: `router → service → repository → models`. Os módulos se comunicam pelos **services** e por **eventos de domínio** (ex.: `ticket.created`), nunca acessando diretamente os repositórios de outro módulo.

## Eventos de domínio

Toda mudança relevante gera um evento gravado **na mesma transação** em `ticket_events` (histórico/auditoria) e em `outbox` (padrão *transactional outbox*). O worker lê o outbox e dispara:

- notificações por e-mail e no sistema
- no futuro: webhooks de saída e tarefas de IA (classificar, gerar embedding, resumir)

Assim nenhuma notificação é enviada para uma transação que deu rollback, e nenhum evento se perde se o processo cair.

## Segurança

- RBAC no nível de serviço (não só na rota) e filtros de visibilidade aplicados nas consultas
- Opcionalmente, Row-Level Security do PostgreSQL como segunda camada (avaliar na Fase 2)
- Anexos: limite de tamanho, verificação de tipo pelo conteúdo real, armazenamento em disco local, download só pela API com verificação de permissão
- Rate limiting por usuário e por IP
- Segredos (senha do SMTP e, no futuro, chave da API de IA) criptografados em repouso ou fornecidos via variáveis de ambiente / gerenciador de segredos

## Implantação

Cada empresa tem a **sua própria instalação**: aplicação e banco de dados próprios (ver [ADR 0005](adr/0005-instalacao-por-empresa.md)). Na Martiniti, tudo roda **em um único servidor Linux** ([ADR 0010](adr/0010-producao-systemd.md)):

```
navegador ──HTTPS──► nginx ──► uvicorn (sistema-chamados.service) ──► PostgreSQL 17
                                    │  API + SPA (frontend/dist)          ▲
                                    │                                     │
                     sistema-chamados-worker.service ─────────────────────┘
                     (fila de tarefas, e-mails, rotinas)
```

- A SPA compilada é servida pelo próprio uvicorn, **na mesma origem** da API: sem CORS e com o cookie de sessão funcionando sem configuração extra.
- Logs vão para o journald (`journalctl -u sistema-chamados`).
- **Atualização:** `scripts/deploy.sh` (git pull, dependências, build do frontend, migrações). Quem reinicia os serviços é o usuário.
- **Desenvolvimento:** `docker compose` (PostgreSQL 17, Mailpit para capturar e-mails), backend com `uvicorn --reload` e frontend com `pnpm dev` (Vite).
- **Backup:** `pg_dump` diário + cópia de `/var/lib/sistema-chamados/files`.
