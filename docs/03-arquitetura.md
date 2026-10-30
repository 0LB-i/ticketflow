# 3. Arquitetura

Princípios, escolhas de tecnologia e arquitetura-alvo. Para o mapa do código como ele está hoje, veja o [ARCHITECTURE.md](../ARCHITECTURE.md).

## Princípios

1. **API-first.** Toda funcionalidade existe primeiro na API REST. As telas, renderizadas no servidor, chamam as mesmas funções das rotas da API e não têm regra própria ([ADR 0011](adr/0011-interface-web-no-servidor.md)). Tudo o que a tela faz também pode ser feito pela API, o que deixa o caminho pronto para integrações e agentes de IA depois da v1.0.
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
| Banco | PostgreSQL 17 (suporte a 16), com o JIT desligado nas conexões do aplicativo | Ver [ADR 0003](adr/0003-postgresql.md) e [ADR 0012](adr/0012-postgresql-sem-jit.md) |
| Busca textual | `tsvector` com a configuração `pt_br` (`portuguese` + `unaccent`, já criada na migração 0001) | Nativo, sem serviço extra. Entra na Sprint 4 |
| Busca vetorial (futuro) | `pgvector` (HNSW) | Nativo, sem serviço extra. Entra com a IA |
| Fila de tarefas | Fila própria: tabelas `outbox` e `jobs` no PostgreSQL + `SKIP LOCKED` (a biblioteca *Procrastinate* foi avaliada e descartada: schema fora do Alembic e sem outbox) | Sem broker extra; transacional com os dados. Desde a Sprint 4 ([ARCHITECTURE 3.12](../ARCHITECTURE.md#312-worker-outbox-e-fila-de-tarefas-modulesjobs)) |
| Cliente HTTP | httpx | Async; usado no futuro para webhooks e para a API de IA |
| Autenticação | E-mail e senha (Argon2id) + sessão no servidor; TOTP para MFA | A primeira instalação não tem diretório de contas; SSO fica para o futuro |
| Interface web | Jinja2 + HTMX + Tailwind CSS (binário standalone, sem Node), JavaScript puro sem build | Telas renderizadas pelo próprio FastAPI, uma linguagem só. Ver [ADR 0011](adr/0011-interface-web-no-servidor.md) (substitui os ADRs 0007 e 0008, da SPA em Vue) |
| Editor de texto | Tiptap gravando Markdown; exibição com `markdown-it-py` sem HTML bruto | Formatação sem o usuário saber Markdown (questão 4, decidida em 2026-10-10) |
| Idiomas | Catálogos JSON das telas (`web/locales/`) e catálogo de mensagens da API (`core/i18n.py`); português e inglês | Idioma padrão nas Configurações; cada pessoa escolhe o seu |
| IA (futuro) | Cliente HTTP genérico no formato compatível com OpenAI | Sem acoplamento a provedor ou modelo. Ver [ADR 0004](adr/0004-ia-api-generica-e-assistiva.md) |
| Gerência de pacotes | uv | Rápido, lockfile reprodutível |
| Qualidade (backend) | ruff, mypy (strict), pytest com PostgreSQL real (16 e 17) | Ver [12.7](12-processo-de-desenvolvimento.md#127-estratégia-de-testes) |
| Qualidade (telas) | Testes do HTML no pytest (`tests/telas`); Playwright para os testes ponta a ponta, quando entrarem | |
| Observabilidade | structlog (logs estruturados no journald); OpenTelemetry e métricas só se houver necessidade | |
| Execução | systemd + uvicorn atrás do nginx; sem Docker (nem em desenvolvimento) | Ver [ADR 0010](adr/0010-producao-systemd.md) |

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
- `scheduler`: tarefas periódicas (lembretes de aprovação, limpeza de uploads). Roda dentro do worker: cada rotina do dia entra na fila com uma chave única (`dedup_key`), o que garante uma execução só mesmo com mais de um worker

## Estrutura de código

A estrutura **como ela é hoje** (pastas, módulos, camadas, fluxo de uma requisição, regras e receitas) está no [ARCHITECTURE.md](../ARCHITECTURE.md), na raiz do repositório. Este documento guarda os princípios, as escolhas e o que está planejado.

Diferenças em relação ao desenho original:

- **Sem camada de repository:** rotas simples (cadastros) trabalham no próprio `router.py`; quando há regra de negócio, a rota chama um `service.py`, que usa o SQLAlchemy diretamente. Fluxo: `router → service → models`.
- O **filtro de visibilidade** e as **ações permitidas** de um chamado ficam no módulo `tickets` (`visibility.py` e `rules.py`); o catálogo de permissões e o `can()` ficam em `core/permissions.py`.
- As **configurações da instalação** (idioma, cores, logotipo) formam o módulo `system`.
- Módulo que ainda não existe: `knowledge` (entra conforme o [roadmap](07-roadmap.md)).

As telas (`web/`) não contêm regra de negócio: chamam as funções da API ou os services e só montam o HTML; a validação que vale é a da API.

## Eventos de domínio

Toda mudança relevante gera um evento gravado **na mesma transação** em `ticket_events` (histórico/auditoria; já implementado) e em `outbox` (padrão *transactional outbox*; desde a Sprint 4). O worker lê o outbox e dispara:

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

Cada empresa tem a **sua própria instalação**: aplicação e banco de dados próprios (ver [ADR 0005](adr/0005-instalacao-por-empresa.md)). Na primeira instalação, tudo roda **em um único servidor Linux** ([ADR 0010](adr/0010-producao-systemd.md)):

```
navegador ──HTTPS──► nginx ──► uvicorn (ticketflow.service) ──► PostgreSQL 17
                                    │  API + telas (Jinja2 + HTMX)        ▲
                                    │                                     │
                     ticketflow-worker.service ─────────────────────┘
                     (fila de tarefas, e-mails, rotinas)
```

- As telas são servidas pelo próprio uvicorn, **na mesma origem** da API: sem CORS e com o cookie de sessão funcionando sem configuração extra.
- Logs vão para o journald (`journalctl -u ticketflow`).
- **Atualização:** `update.sh` na raiz (busca a `main`, dependências, CSS das telas, migrações; `--force` descarta as mudanças locais). Quem reinicia os serviços é o usuário.
- **Desenvolvimento:** PostgreSQL 17 e 16 nativos (numa máquina nova, `scripts/preparar-maquina-dev.sh`), `uvicorn --reload` e `scripts/css.sh --watch` (o CSS das telas); ou o serviço systemd local, instalado por `scripts/instalar-servico-dev.sh` ([README](../README.md#como-rodar-desenvolvimento)).
- **Backup:** fora do programa; quem administra o servidor copia o banco e `/var/lib/ticketflow/files` ([18.5](18-manual-do-servidor.md#185-backup)).
