# Sistema de Chamados

Sistema interno de chamados (help desk / service desk) para empresas, escrito em **Python** com **PostgreSQL 16/17**, projetado desde o início para se integrar a **IAs via API**.

> **Status:** em planejamento. Este repositório contém, por enquanto, apenas a documentação de planejamento. O código entra a partir da Fase 0 do [roadmap](docs/07-roadmap.md).

## Documentação

| # | Documento | Conteúdo |
|---|-----------|----------|
| 1 | [Visão geral](docs/01-visao-geral.md) | Problema, objetivos, público, escopo |
| 2 | [Requisitos](docs/02-requisitos.md) | Requisitos funcionais e não funcionais |
| 3 | [Arquitetura](docs/03-arquitetura.md) | Stack, camadas, componentes, implantação |
| 4 | [Modelo de dados](docs/04-modelo-de-dados.md) | Entidades e esboço do schema PostgreSQL |
| 5 | [API](docs/05-api.md) | Convenções REST, autenticação, endpoints, webhooks |
| 6 | [Integração com IA](docs/06-integracao-ia.md) | Casos de uso, arquitetura, segurança e LGPD |
| 7 | [Roadmap](docs/07-roadmap.md) | Fases, entregas e critérios de pronto |
| — | [Questões em aberto](docs/questoes-em-aberto.md) | Decisões ainda pendentes |
| — | [ADRs](docs/adr/) | Registro de decisões de arquitetura |

## Stack proposta

- **Linguagem:** Python 3.12+
- **API:** FastAPI + Pydantic v2
- **Banco:** PostgreSQL 17 (compatível com 16) + extensão `pgvector`; uma instalação por empresa
- **Acesso a dados:** SQLAlchemy 2.x + psycopg 3, migrações com Alembic
- **Tarefas assíncronas:** fila no próprio PostgreSQL (`SELECT ... FOR UPDATE SKIP LOCKED`)
- **Interface web:** SPA em Vue 3 + TypeScript + Vite + Tailwind CSS, consumindo a API REST
- **IA:** uma única API genérica (formato compatível com OpenAI), configurada por URL, chave e nome do modelo, sem código específico de provedor

Detalhes e justificativas em [docs/03-arquitetura.md](docs/03-arquitetura.md) e nos [ADRs](docs/adr/).

## Ambiente local (banco)

```bash
docker compose up -d db     # PostgreSQL 17 com pgvector em localhost:5432
```

## Convenções

- Documentação em **português**; identificadores de código e banco em **inglês** (`ticket`, `comment`, `assignee`). Ver [ADR 0001](docs/adr/0001-registro-de-decisoes.md).
- Decisões relevantes viram um ADR em `docs/adr/` (status: proposta → aceita / rejeitada / substituída).
- Commits seguindo [Conventional Commits](https://www.conventionalcommits.org/pt-br/) (`feat:`, `fix:`, `docs:` …).
