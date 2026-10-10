# Sistema de Chamados

Sistema interno de chamados (help desk / service desk) para empresas, escrito em **Python** com **PostgreSQL 16/17**, com arquitetura preparada para se integrar a **IAs via API** depois da versão 1.0.

> **Status:** em planejamento. Este repositório contém, por enquanto, apenas a documentação de planejamento. O código entra a partir da Fase 0 do [roadmap](docs/07-roadmap.md).

## Documentação

| # | Documento | Conteúdo |
|---|-----------|----------|
| 1 | [Visão geral](docs/01-visao-geral.md) | Problema, objetivos, público, escopo |
| 2 | [Requisitos](docs/02-requisitos.md) | Requisitos funcionais e não funcionais |
| 3 | [Arquitetura](docs/03-arquitetura.md) | Stack, camadas, componentes, implantação |
| 4 | [Modelo de dados](docs/04-modelo-de-dados.md) | Entidades e esboço do schema PostgreSQL |
| 5 | [API](docs/05-api.md) | Convenções REST, autenticação, endpoints; webhooks (futuro) |
| 6 | [Integração com IA](docs/06-integracao-ia.md) | Plano para depois da v1.0: casos de uso, arquitetura, segurança e LGPD |
| 7 | [Roadmap](docs/07-roadmap.md) | Fases, sprints, entregas e critérios de pronto |
| 8 | [Organização e permissões](docs/08-organizacao-e-permissoes.md) | Setores, grupos, papéis, permissões e visibilidade |
| 9 | [Login e autenticação](docs/09-login-e-autenticacao.md) | Login por e-mail e senha, MFA, sessões |
| 10 | [Como funcionam os chamados](docs/10-chamados.md) | Abertura, status, fluxo, trabalho do agente, aprovações, notificações |
| 11 | [Anexos e arquivos](docs/11-anexos-e-arquivos.md) | Onde se anexa, tipos, limites, armazenamento, permissões |
| 12 | [Processo de desenvolvimento](docs/12-processo-de-desenvolvimento.md) | GitHub, commits, CI, implantação, definição de pronto, testes |
| 13 | [Telas e navegação](docs/13-telas-e-navegacao.md) | Mapa de telas, menus por perfil, rascunhos e padrões de interação |
| 14 | [Relatórios e indicadores](docs/14-relatorios-e-indicadores.md) | Indicadores, painéis por perfil e exportações |
| 15 | [Estrutura da empresa](docs/15-estrutura-inicial.md) | Modelo para a carga inicial: setores, grupos, categorias, usuários |
| — | [Glossário](docs/glossario.md) | Termos do domínio e nomes no código |
| — | [Questões em aberto](docs/questoes-em-aberto.md) | Decisões ainda pendentes |
| — | [ADRs](docs/adr/) | Registro de decisões de arquitetura |

## Stack proposta

- **Linguagem:** Python 3.12+
- **API:** FastAPI + Pydantic v2
- **Banco:** PostgreSQL 17 (compatível com 16); uma instalação por empresa
- **Acesso a dados:** SQLAlchemy 2.x + psycopg 3, migrações com Alembic
- **Tarefas assíncronas:** fila no próprio PostgreSQL (`SELECT ... FOR UPDATE SKIP LOCKED`)
- **Interface web:** SPA em Vue 3 + TypeScript + Vite + Tailwind CSS + Reka UI, consumindo a API REST
- **Plataforma:** GitHub (código, Actions, Projects)
- **Produção:** serviços systemd (uvicorn) + nginx + PostgreSQL 17 no mesmo servidor
- **IA (depois da v1.0):** uma única API genérica (formato compatível com OpenAI), configurada por URL, chave e nome do modelo, sem código específico de provedor

Detalhes e justificativas em [docs/03-arquitetura.md](docs/03-arquitetura.md) e nos [ADRs](docs/adr/).

## Ambiente de desenvolvimento (banco)

```bash
docker compose up -d db     # PostgreSQL 17 em localhost:5432
```

## Convenções

- Documentação em **português**; identificadores de código e banco em **inglês** (`ticket`, `comment`, `assignee`). Ver [ADR 0001](docs/adr/0001-registro-de-decisoes.md).
- Decisões relevantes viram um ADR em `docs/adr/` (status: proposta → aceita / rejeitada / substituída).
- Commits seguindo [Conventional Commits](https://www.conventionalcommits.org/pt-br/) (`feat:`, `fix:`, `docs:` …).
