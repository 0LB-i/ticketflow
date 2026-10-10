# TicketFlow

Sistema interno de chamados para as equipes da empresa, em que os próprios membros registram, distribuem e executam as tarefas. Escrito em **Python** com **PostgreSQL 16/17**, com arquitetura preparada para se integrar a **IAs via API** depois da versão 1.0.

> **Status:** Fase 1 (MVP) do [roadmap](docs/07-roadmap.md): fundação, identidade e organização, núcleo dos chamados e configurações (idioma, cores, logotipo) prontos; a próxima é a Sprint 4 (anexos, notificações, filas e busca). O andamento de cada item está em [TAREFAS.md](TAREFAS.md).

## Documentação

| # | Documento | Conteúdo |
|---|-----------|----------|
| — | [**ARCHITECTURE.md**](ARCHITECTURE.md) | **Guia da estrutura do código**: pastas, módulos, camadas, permissões, contrato da API, testes, regras e receitas |
| 1 | [Visão geral](docs/01-visao-geral.md) | Problema, objetivos, público, escopo |
| 2 | [Requisitos](docs/02-requisitos.md) | Requisitos funcionais e não funcionais |
| 3 | [Arquitetura](docs/03-arquitetura.md) | Princípios, stack, arquitetura-alvo, implantação |
| 4 | [Modelo de dados](docs/04-modelo-de-dados.md) | Entidades e esboço do schema PostgreSQL |
| 5 | [API](docs/05-api.md) | Convenções REST, autenticação, endpoints; webhooks (futuro) |
| 6 | [Integração com IA](docs/06-integracao-ia.md) | Plano para depois da v1.0: casos de uso, arquitetura, segurança e LGPD |
| 7 | [Roadmap](docs/07-roadmap.md) | Fases, sprints, entregas e critérios de pronto |
| 8 | [Organização e permissões](docs/08-organizacao-e-permissoes.md) | Grupos, setores atendidos, papéis, permissões e visibilidade |
| 9 | [Login e autenticação](docs/09-login-e-autenticacao.md) | Login por e-mail e senha, MFA, sessões |
| 10 | [Como funcionam os chamados](docs/10-chamados.md) | Registro, status, fluxo, trabalho da equipe, aprovações, notificações |
| 11 | [Anexos e arquivos](docs/11-anexos-e-arquivos.md) | Onde se anexa, tipos, limites, armazenamento, permissões |
| 12 | [Processo de desenvolvimento](docs/12-processo-de-desenvolvimento.md) | Repositório local, tarefas, commits, verificação local, definição de pronto, testes |
| 13 | [Telas e navegação](docs/13-telas-e-navegacao.md) | Mapa de telas, menus por perfil, rascunhos e padrões de interação |
| 14 | [Relatórios e indicadores](docs/14-relatorios-e-indicadores.md) | Indicadores, painéis por perfil e exportações |
| 15 | [Estrutura da empresa](docs/15-estrutura-inicial.md) | Modelo para a carga inicial: grupos, usuários, setores atendidos, categorias |
| 16 | [Plano de implantação](docs/16-implantacao.md) | Virada da TI, treinamento, combinados, acompanhamento e expansão |
| 17 | [Identidade visual](docs/17-identidade-visual.md) | Nome, cores, contraste, tipografia, logotipo e e-mails |
| 18 | [Manual do servidor](docs/18-manual-do-servidor.md) | Instalação no Ubuntu 24.04, atualização, backup, rotina e problemas comuns |
| — | [Glossário](docs/glossario.md) | Termos do domínio e nomes no código |
| — | [Questões em aberto](docs/questoes-em-aberto.md) | Decisões ainda pendentes |
| — | [ADRs](docs/adr/) | Registro de decisões de arquitetura |

## Stack

- **Linguagem:** Python 3.12+
- **API:** FastAPI + Pydantic v2
- **Banco:** PostgreSQL 17 (compatível com 16); uma instalação por empresa
- **Acesso a dados:** SQLAlchemy 2.x + psycopg 3, migrações com Alembic
- **Tarefas assíncronas:** fila no próprio PostgreSQL (`SELECT ... FOR UPDATE SKIP LOCKED`)
- **Interface web:** SPA em Vue 3 + TypeScript + Vite + Tailwind CSS + Reka UI, consumindo a API REST; editor Tiptap (Markdown)
- **Idiomas:** português e inglês (padrão do sistema + escolha de cada usuário)
- **Repositório:** Git local, com verificação por script; GitHub quando houver remoto
- **Produção:** serviços systemd (uvicorn) + nginx + PostgreSQL 17 no mesmo servidor
- **IA (depois da v1.0):** uma única API genérica (formato compatível com OpenAI), configurada por URL, chave e nome do modelo, sem código específico de provedor

A estrutura do código está no [ARCHITECTURE.md](ARCHITECTURE.md); as justificativas, em [docs/03-arquitetura.md](docs/03-arquitetura.md) e nos [ADRs](docs/adr/).

## Como rodar (desenvolvimento)

Requisitos: [uv](https://docs.astral.sh/uv/), Node.js 22 com `corepack enable` (pnpm) e PostgreSQL 17 em `localhost:5432` com o usuário `chamados` / senha `chamados` e os bancos `chamados` e `chamados_test`.

O PostgreSQL pode ser nativo (como nesta máquina de desenvolvimento, com o 16 também na porta 5433 para a verificação completa) ou do Docker:

```bash
docker compose up -d db                 # alternativa ao PostgreSQL nativo
```

```bash
# backend: API em http://127.0.0.1:8000 (documentação em /api/docs)
cd backend
cp .env.example .env
uv sync
uv run chamados db upgrade              # cria o administrador padrão: usuário admin, senha admin
uv run uvicorn chamados.main:create_app --factory --reload

# frontend, em outro terminal: http://localhost:5173 (o Vite repassa /api para o backend)
# entre com admin / admin: o sistema pede a troca da senha no primeiro acesso
cd frontend
pnpm install
pnpm dev
```

Depois de mudar a API no backend: `pnpm gen:api` (no `frontend/`) regenera o cliente TypeScript.

**Como serviço, sem deixar terminais abertos:** `sudo scripts/instalar-servico-dev.sh` instala o `sistema-chamados.service` (a mesma unit da produção, escutando na rede na porta 8000, sem nginx), compila o frontend e aplica as migrações. Rodar de novo atualiza; depois, `sudo systemctl restart sistema-chamados`.

### Verificação

```bash
scripts/install-hooks.sh                # uma vez: verificação rápida antes de cada commit
scripts/check.sh                        # antes de concluir uma tarefa ou enviar ao servidor
scripts/check.sh --completo             # antes de uma versão: também PostgreSQL 16 e auditoria
```

Detalhes em [Processo de desenvolvimento](docs/12-processo-de-desenvolvimento.md#123-verificação-local-no-lugar-do-ci). Produção: [Manual do servidor](docs/18-manual-do-servidor.md).

## Convenções

- Documentação em **português**; identificadores de código e banco em **inglês** (`ticket`, `comment`, `assignee`). Ver [ADR 0001](docs/adr/0001-registro-de-decisoes.md).
- Decisões relevantes viram um ADR em `docs/adr/` (status: proposta → aceita / rejeitada / substituída).
- Commits seguindo [Conventional Commits](https://www.conventionalcommits.org/pt-br/) (`feat:`, `fix:`, `docs:` …).
