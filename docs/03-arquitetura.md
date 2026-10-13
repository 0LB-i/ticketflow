# 3. Arquitetura

Princípios, escolhas de tecnologia e arquitetura-alvo. Para o mapa do código como ele está hoje, veja o [ARCHITECTURE.md](../ARCHITECTURE.md).

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
| Busca textual | `tsvector` com a configuração `pt_br` (`portuguese` + `unaccent`, já criada na migração 0001) | Nativo, sem serviço extra. Entra na Sprint 4 |
| Busca vetorial (futuro) | `pgvector` (HNSW) | Nativo, sem serviço extra. Entra com a IA |
| Fila de tarefas | Tabela no PostgreSQL + `SKIP LOCKED` (avaliar a biblioteca *Procrastinate*) | Sem broker extra; transacional com os dados. Entra na Sprint 4 |
| Cliente HTTP | httpx | Async; usado no futuro para webhooks e para a API de IA |
| Autenticação | E-mail e senha (Argon2id) + sessão no servidor; TOTP para MFA | A Martiniti não tem diretório de contas; SSO fica para o futuro |
| Interface web | Vue 3 + TypeScript + Vite + Tailwind CSS + Reka UI, Vue Router, Pinia, TanStack Query | SPA consumindo a API. Ver [ADR 0007](adr/0007-interface-web-vue.md) e [ADR 0008](adr/0008-reka-ui.md) |
| Editor de texto | Tiptap gravando Markdown; exibição com `markdown-it` sem HTML bruto | Formatação sem o usuário saber Markdown (questão 4, decidida em 2026-10-10) |
| Idiomas | vue-i18n (interface) e catálogo de mensagens no backend (`core/i18n.py`); português e inglês | Idioma padrão nas Configurações; cada pessoa escolhe o seu |
| Cliente da API no frontend | Tipos gerados do OpenAPI (`openapi-typescript` + `openapi-fetch`) | O contrato do backend vira tipos TypeScript; mudança incompatível quebra o build |
| IA (futuro) | Cliente HTTP genérico no formato compatível com OpenAI | Sem acoplamento a provedor ou modelo. Ver [ADR 0004](adr/0004-ia-api-generica-e-assistiva.md) |
| Gerência de pacotes | uv | Rápido, lockfile reprodutível |
| Qualidade (backend) | ruff, mypy (strict), pytest com PostgreSQL real (16 e 17) | Ver [12.7](12-processo-de-desenvolvimento.md#127-estratégia-de-testes) |
| Qualidade (frontend) | ESLint, Prettier, vue-tsc, Vitest, Playwright (testes ponta a ponta) | |
| Observabilidade | structlog (logs estruturados no journald); OpenTelemetry e métricas só se houver necessidade | |
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

## Estrutura de código

A estrutura **como ela é hoje** (pastas, módulos, camadas, fluxo de uma requisição, regras e receitas) está no [ARCHITECTURE.md](../ARCHITECTURE.md), na raiz do repositório. Este documento guarda os princípios, as escolhas e o que está planejado.

Diferenças em relação ao desenho original:

- **Sem camada de repository:** rotas simples (cadastros) trabalham no próprio `router.py`; quando há regra de negócio, a rota chama um `service.py`, que usa o SQLAlchemy diretamente. Fluxo: `router → service → models`.
- O **filtro de visibilidade** e as **ações permitidas** de um chamado ficam no módulo `tickets` (`visibility.py` e `rules.py`); o catálogo de permissões e o `can()` ficam em `core/permissions.py`.
- As **configurações da instalação** (idioma, cores, logotipo) formam o módulo `system`.
- Módulos que ainda não existem: `attachments`, `knowledge`, `reports` e o `worker` (entram conforme o [roadmap](07-roadmap.md)).

O backend não conhece o frontend: só expõe a API. O frontend nunca contém regra de negócio além de validação de formulário para dar retorno rápido; a validação que vale é a da API.

## Eventos de domínio

Toda mudança relevante gera um evento gravado **na mesma transação** em `ticket_events` (histórico/auditoria; já implementado) e em `outbox` (padrão *transactional outbox*; entra com o worker na Sprint 4). O worker lê o outbox e dispara:

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
navegador ──HTTPS──► nginx ──► uvicorn (ticketflow.service) ──► PostgreSQL 17
                                    │  API + SPA (frontend/dist)          ▲
                                    │                                     │
                     ticketflow-worker.service ─────────────────────┘
                     (fila de tarefas, e-mails, rotinas)
```

- A SPA compilada é servida pelo próprio uvicorn, **na mesma origem** da API: sem CORS e com o cookie de sessão funcionando sem configuração extra.
- Logs vão para o journald (`journalctl -u ticketflow`).
- **Atualização:** `scripts/deploy.sh` (git pull, dependências, build do frontend, migrações). Quem reinicia os serviços é o usuário.
- **Desenvolvimento:** PostgreSQL nativo ou `docker compose` (PostgreSQL 17, Mailpit para capturar e-mails), backend com `uvicorn --reload` e frontend com `pnpm dev` (Vite); ou o serviço systemd local, instalado por `scripts/instalar-servico-dev.sh` ([README](../README.md#como-rodar-desenvolvimento)).
- **Backup:** `pg_dump` diário + cópia de `/var/lib/ticketflow/files`.
