# TicketFlow

Sistema interno de chamados para as equipes de uma empresa, em que os próprios membros registram, distribuem e executam as tarefas. Escrito em **Python** com **PostgreSQL 16/17**, com arquitetura preparada para se integrar a **IAs via API** depois da versão 1.0.

> **Status:** Fase 1 (MVP) do [roadmap](docs/07-roadmap.md), na Sprint 5 (ciclo completo e preparação do piloto): fundação, identidade e organização, núcleo dos chamados, anexos, notificações, filas e busca prontos, e as telas já renderizadas no servidor ([ADR 0011](docs/adr/0011-interface-web-no-servidor.md)). Faltam a instalação no servidor de produção, a carga inicial e o treinamento. O andamento de cada item está em [TAREFAS.md](TAREFAS.md).

## O que o sistema faz

- **Chamados:** registro com grupo, categoria, cliente e responsáveis; tarefas com o tempo gasto, @menções, observadores e anexos; assumir, atribuir, transferir, aguardar, concluir, reabrir e cancelar; histórico de tudo.
- **Filas e Kanban:** filas (Não atribuídos, Meus, Com novidades, Aguardando, Acompanhando, Todos) com busca em português, e o quadro por status em `/quadro`.
- **Relatórios** (`/relatorios`): produtividade, clientes (com as horas no plano do contrato e as excedentes), horas extras e indicadores de chamados, com filtros, comparação de períodos e PDF; a aba Clientes geral gera o relatório de cada cliente e o ZIP com todos os PDFs.
- **Notificações por e-mail**, enviadas pelo worker no idioma de quem recebe.
- **Administração:** usuários, grupos, papéis e permissões, clientes, categorias, status, expediente, dados da empresa, idioma, cores e logotipo, e a auditoria.
- **Integrações:** API REST com tokens por pessoa (`/api/openapi.json`) e servidor MCP em `/mcp`, para assistentes de IA.

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
| 8 | [Organização e permissões](docs/08-organizacao-e-permissoes.md) | Grupos, papéis, permissões e visibilidade |
| 9 | [Login e autenticação](docs/09-login-e-autenticacao.md) | Login por e-mail e senha, MFA, sessões |
| 10 | [Como funcionam os chamados](docs/10-chamados.md) | Registro, status, fluxo, trabalho da equipe, aprovações, notificações |
| 11 | [Anexos e arquivos](docs/11-anexos-e-arquivos.md) | Onde se anexa, tipos, limites, armazenamento, permissões |
| 12 | [Processo de desenvolvimento](docs/12-processo-de-desenvolvimento.md) | Repositório local, tarefas, commits, verificação local, definição de pronto, testes |
| 13 | [Telas e navegação](docs/13-telas-e-navegacao.md) | Mapa de telas, menus por perfil, rascunhos e padrões de interação |
| 14 | [Relatórios e indicadores](docs/14-relatorios-e-indicadores.md) | Indicadores, painéis por perfil e exportações |
| 15 | [Estrutura inicial](docs/15-estrutura-inicial.md) | Modelo para a carga inicial: grupos, usuários, categorias |
| 16 | [Plano de implantação](docs/16-implantacao.md) | Virada da TI, treinamento, combinados, acompanhamento e expansão |
| 17 | [Identidade visual](docs/17-identidade-visual.md) | Nome, cores, contraste, tipografia, logotipo e e-mails |
| 18 | [Manual do servidor](docs/18-manual-do-servidor.md) | Instalação no Ubuntu 24.04, atualização, rotina e problemas comuns |
| — | [Glossário](docs/glossario.md) | Termos do domínio e nomes no código |
| — | [Questões em aberto](docs/questoes-em-aberto.md) | Decisões ainda pendentes |
| — | [ADRs](docs/adr/) | Registro de decisões de arquitetura |

## Stack

- **Linguagem:** Python 3.12+
- **API:** FastAPI + Pydantic v2
- **Banco:** PostgreSQL 17 (compatível com 16); uma instalação por empresa
- **Acesso a dados:** SQLAlchemy 2.x + psycopg 3, migrações com Alembic
- **Tarefas assíncronas:** fila no próprio PostgreSQL (`SELECT ... FOR UPDATE SKIP LOCKED`)
- **Interface web:** telas renderizadas no servidor com Jinja2 + HTMX + Tailwind CSS (binário standalone, sem Node), [ADR 0011](docs/adr/0011-interface-web-no-servidor.md); editor Tiptap (Markdown). A API REST continua para integrações
- **Idiomas:** português e inglês (padrão do sistema + escolha de cada usuário)
- **Repositório:** [GitHub](https://github.com/0LB-i/ticketflow), com a verificação por script na própria máquina (sem CI); os commits vão direto para a `main`
- **Produção:** serviços systemd (uvicorn) + nginx + PostgreSQL 17 no mesmo servidor
- **IA (depois da v1.0):** uma única API genérica (formato compatível com OpenAI), configurada por URL, chave e nome do modelo, sem código específico de provedor

A estrutura do código está no [ARCHITECTURE.md](ARCHITECTURE.md); as justificativas, em [docs/03-arquitetura.md](docs/03-arquitetura.md) e nos [ADRs](docs/adr/).

## Instalação em produção (VM)

Numa VM com **Ubuntu 24.04 LTS** nova (8 vCPU, 4 GB de RAM e 50 GB de disco, [docs/18 §18.2](docs/18-manual-do-servidor.md#182-requisitos)), com acesso ao GitHub:

```bash
curl -fsSLO https://raw.githubusercontent.com/0LB-i/ticketflow/main/install.sh
sudo bash install.sh                    # domínio padrão ticketflow.local; ou: sudo bash install.sh DOMINIO
```

O script instala o PostgreSQL 17, o uv, o nginx e o código em `/opt/ticketflow` (só o que a produção usa: sem testes, benchmark e `docs/`), cria o `/etc/ticketflow/env`, o banco e os serviços `ticketflow` e `ticketflow-worker`, e publica o sistema em HTTPS com um certificado autoassinado. Numa máquina ainda em UTC, acerta o fuso para `America/Sao_Paulo` (outro: `sudo FUSO=America/Manaus bash install.sh`). Pode rodar de novo: mantém a configuração, o banco e o certificado.

Logo depois:

1. **Entre com `admin` / `admin` e troque a senha:** até lá, qualquer pessoa que alcance o servidor entra como administrador.
2. **Configure o SMTP** no `/etc/ticketflow/env` (sem ele, convites e notificações não saem) e reinicie: `sudo systemctl restart ticketflow` (o worker vai junto).
3. **Domínio e certificado definitivos:** `server_name` e certificado em `/etc/nginx/sites-available/ticketflow` (ou `certbot --nginx -d DOMINIO`), `APP_BASE_URL` no `/etc/ticketflow/env`, e então `sudo systemctl reload nginx && sudo systemctl restart ticketflow`.

**Atualizar** para a versão mais nova da `main` (baixa o código, instala as dependências, gera o CSS e aplica as migrações; quem reinicia é o administrador):

```bash
sudo -u ticketflow /opt/ticketflow/scripts/deploy.sh && sudo systemctl restart ticketflow
```

Estado e log: `systemctl status ticketflow ticketflow-worker` e `journalctl -u ticketflow -u ticketflow-worker -f`. Backup, rotina e problemas comuns no [Manual do servidor](docs/18-manual-do-servidor.md).

## Como rodar (desenvolvimento)

**Máquina nova (Ubuntu 24.04):** um script instala tudo o que está abaixo (uv, PostgreSQL 17 e 16, usuário e bancos de desenvolvimento), clona o código em `/opt/ticketflow`, instala as dependências e o hook de pre-commit e cria uma chave para enviar commits ao GitHub:

```bash
curl -fsSLO https://raw.githubusercontent.com/0LB-i/ticketflow/main/scripts/preparar-maquina-dev.sh
sudo bash preparar-maquina-dev.sh              # com --servico, instala também o ticketflow.service
```

No fim ele mostra a chave pública, para cadastrar no GitHub como *deploy key* com escrita (Settings → Deploy keys).

Requisitos: [uv](https://docs.astral.sh/uv/) e PostgreSQL 17 em `localhost:5432` com o usuário `chamados` / senha `chamados` e os bancos `chamados` e `chamados_test`.

O PostgreSQL 16 também fica instalado, na porta 5433, para a verificação completa.

```bash
# http://127.0.0.1:8000: as telas e a API (especificação da API em /api/openapi.json)
# entre com admin / admin: o sistema pede a troca da senha no primeiro acesso
cd backend
cp .env.example .env
uv sync
uv run chamados db upgrade              # cria o administrador padrão: usuário admin, senha admin
uv run uvicorn chamados.main:create_app --factory --reload

# CSS das telas (Tailwind), gerado de novo a cada mudança nos templates; em outro terminal, na raiz
scripts/css.sh --watch

# worker (fila de tarefas e rotinas diárias), quando precisar dele; em outro terminal, em backend/
uv run chamados worker
```

**Como serviço, sem deixar terminais abertos:** `sudo scripts/instalar-servico-dev.sh` instala três serviços em modo de desenvolvimento, atrás do nginx em `https://IP` (a porta 80 redireciona para a 443): o `ticketflow.service` (o uvicorn em `127.0.0.1:8001` com `--reload`, que reinicia sozinho quando um `.py` muda; o nginx manda tudo para ele) o `ticketflow-css.service` (o Tailwind gerando de novo o CSS das telas a cada mudança nos templates) e o `ticketflow-worker.service` (o worker, que acompanha o `ticketflow` e reinicia sozinho quando um `.py` muda). Também instala o Mailpit (`mailpit.service`): os e-mails do sistema aparecem em `https://IP:8025` (usuário `ticketflow`; a senha fica em `/etc/ticketflow/mailpit-senha`, só para o root), e nenhum sai da máquina. Numa instalação antiga, ele também desativa e apaga o `ticketflow-frontend.service` (o Vite, que saiu com a SPA). O certificado é autoassinado (`/etc/ticketflow/tls/ticketflow.crt`): instale-o como confiável no computador para o navegador não avisar. Não há build nem reinício a cada mudança (basta recarregar a página); só as migrações são aplicadas à mão (`.venv/bin/chamados db upgrade`, com o `/etc/ticketflow/env`). Rodar o script de novo atualiza as dependências e aplica as migrações.

### Verificação

```bash
scripts/install-hooks.sh                # uma vez: verificação rápida antes de cada commit
scripts/check.sh                        # uma vez, antes do commit: tipos e os testes do que mudou
scripts/check.sh --completo             # antes de uma versão: todos os testes, também no PostgreSQL 16, e auditoria
```

Detalhes em [Processo de desenvolvimento](docs/12-processo-de-desenvolvimento.md#123-verificação-local-no-lugar-do-ci).

## Convenções

- Documentação em **português**; identificadores de código e banco em **inglês** (`ticket`, `comment`, `assignee`). Ver [ADR 0001](docs/adr/0001-registro-de-decisoes.md).
- Decisões relevantes viram um ADR em `docs/adr/` (status: proposta → aceita / rejeitada / substituída).
- Commits seguindo [Conventional Commits](https://www.conventionalcommits.org/pt-br/) (`feat:`, `fix:`, `docs:` …).
