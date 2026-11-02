# TicketFlow

Sistema interno de chamados para as equipes de uma empresa, em que os próprios membros registram, distribuem e executam as tarefas. Escrito em **Python** com **PostgreSQL 16/17**, com arquitetura preparada para se integrar a **IAs via API** depois da versão 1.0.

> **Status:** Fase 1 (MVP) do [roadmap](docs/07-roadmap.md); faltam a instalação no servidor de produção, a carga inicial e o treinamento. O andamento de cada item está em [TAREFAS.md](TAREFAS.md).

## Instalação (produção)

Numa VM com **Ubuntu 24.04 LTS** nova (8 vCPU, 4 GB de RAM e 50 GB de disco, [docs/18 §18.2](docs/18-manual-do-servidor.md#182-requisitos)), com acesso ao GitHub:

```bash
curl -fsSLO https://raw.githubusercontent.com/0LB-i/ticketflow/main/install.sh
sudo bash install.sh                    # domínio padrão ticketflow.local; ou: sudo bash install.sh DOMINIO
```

O script instala o PostgreSQL 17, o uv, o nginx e o código em `/opt/ticketflow` (só o que a produção usa: sem testes, benchmark e `docs/`), cria o `/etc/ticketflow/env`, o banco e os serviços `ticketflow` e `ticketflow-worker`, e publica o sistema em HTTPS com um certificado autoassinado. Numa máquina ainda em UTC, acerta o fuso para `America/Sao_Paulo` (outro: `sudo FUSO=America/Manaus bash install.sh`). Pode rodar de novo: mantém a configuração, o banco e o certificado.

O sistema fica em `https://DOMINIO` (ou `https://IP-do-servidor`); até o certificado definitivo, o navegador avisa que o certificado não é confiável. Logo depois:

1. **Entre com `admin` / `admin` e troque a senha:** até lá, qualquer pessoa que alcance o servidor entra como administrador.
2. **Configure o SMTP** no `/etc/ticketflow/env` (sem ele, convites e notificações não saem) e reinicie: `sudo systemctl restart ticketflow` (o worker vai junto).
3. **Domínio e certificado definitivos:** `server_name` e certificado em `/etc/nginx/sites-available/ticketflow` (ou `certbot --nginx -d DOMINIO`), `APP_BASE_URL` no `/etc/ticketflow/env`, e então `sudo systemctl reload nginx && sudo systemctl restart ticketflow`.

## Atualização

Leia antes as notas da versão ([docs/12 §12.5](docs/12-processo-de-desenvolvimento.md#125-versões-e-entregas)). O `update.sh` baixa a versão mais nova da `main`, instala as dependências, gera o CSS e aplica as migrações; quem reinicia é o administrador (a interrupção dura poucos segundos):

```bash
sudo /opt/ticketflow/update.sh && sudo systemctl restart ticketflow
curl -fsS https://DOMINIO/api/health   # confere se voltou
```

Se o código no servidor tiver mudanças locais ou estiver numa versão anterior (`git checkout <tag>`), o `update.sh` para e avisa; `sudo /opt/ticketflow/update.sh --force` descarta essas mudanças e deixa o código igual à `main`. Para voltar à versão anterior, veja [docs/18 §18.4](docs/18-manual-do-servidor.md#184-atualização).

## Operação

- **Estado:** `systemctl status ticketflow ticketflow-worker`
- **Log:** `journalctl -u ticketflow -u ticketflow-worker -f`
- **Backup, rotina e problemas comuns:** [Manual do servidor](docs/18-manual-do-servidor.md)

## O que o sistema faz

- **Chamados:** registro com grupo, categoria, cliente e responsáveis; tarefas com o tempo gasto, @menções, observadores e anexos; assumir, atribuir, transferir, aguardar, concluir, reabrir e cancelar; histórico de tudo.
- **Filas e Kanban:** filas (Não atribuídos, Meus, Com novidades, Aguardando, Acompanhando, Todos) com busca em português, e o quadro por status em `/quadro`.
- **Relatórios** (`/relatorios`): produtividade, clientes (com as horas no plano do contrato e as excedentes), horas extras e indicadores de chamados, com filtros, comparação de períodos e PDF; a aba Clientes geral gera o relatório de cada cliente e o ZIP com todos os PDFs.
- **Notificações por e-mail**, enviadas pelo worker no idioma de quem recebe.
- **Administração:** usuários, grupos, papéis e permissões, clientes, categorias, status, expediente, dados da empresa, idioma, cores e logotipo, e a auditoria.
- **Integrações:** API REST com tokens por pessoa (`/api/openapi.json`) e servidor MCP em `/mcp`, para assistentes de IA.

## Desenvolvimento

Antes de mexer no código, leia o [ARCHITECTURE.md](ARCHITECTURE.md): pastas, camadas, permissões, testes, regras e receitas.

### Máquina nova

Num Ubuntu 24.04, um script instala o uv, o PostgreSQL 17 (porta 5432) e o 16 (porta 5433, para a verificação completa), o usuário e os bancos de desenvolvimento, clona o código em `/opt/ticketflow`, instala as dependências e o hook de pre-commit e cria uma chave para enviar commits ao GitHub:

```bash
curl -fsSLO https://raw.githubusercontent.com/0LB-i/ticketflow/main/scripts/preparar-maquina-dev.sh
sudo bash preparar-maquina-dev.sh              # com --servico, instala também os serviços (abaixo)
```

No fim ele mostra a chave pública, para cadastrar no GitHub como *deploy key* com escrita (Settings → Deploy keys). Depois, escolha um dos dois jeitos de rodar.

### Rodar como serviço (recomendado)

```bash
sudo scripts/instalar-servico-dev.sh
```

Instala os serviços em modo de desenvolvimento, atrás do nginx (a porta 80 redireciona para a 443):

| Serviço | O que faz | Endereço |
|---------|-----------|----------|
| `ticketflow` | uvicorn com `--reload`: reinicia sozinho quando um `.py` muda | `https://IP` (nginx → `127.0.0.1:8001`) |
| `ticketflow-css` | gera de novo o CSS das telas (Tailwind) a cada mudança nos templates | — |
| `ticketflow-worker` | fila de tarefas e rotinas diárias; acompanha o `ticketflow` e reinicia quando um `.py` muda | — |
| `mailpit` | recebe os e-mails do sistema; nenhum sai da máquina | `https://IP:8025` (usuário `ticketflow`, senha em `/etc/ticketflow/mailpit-senha`) |

- **Não há build:** basta recarregar a página para ver uma mudança.
- **Certificado:** autoassinado (`/etc/ticketflow/tls/ticketflow.crt`); instale-o como confiável no computador para o navegador não avisar.
- **Migração nova** é aplicada à mão:
  ```bash
  sudo bash -c 'cd /opt/ticketflow/backend && set -a && . /etc/ticketflow/env && set +a && .venv/bin/chamados db upgrade'
  ```
- Rodar o script de novo atualiza as dependências e aplica as migrações.

### Rodar à mão

Requisitos (o script de máquina nova já os deixa prontos): [uv](https://docs.astral.sh/uv/) e PostgreSQL 17 em `localhost:5432` com o usuário `chamados` / senha `chamados` (com `CREATEDB`: os testes em paralelo criam um banco por worker, `chamados_test_gw0`…) e os bancos `chamados` e `chamados_test`.

```bash
# em backend/: as telas e a API em http://127.0.0.1:8000 (especificação da API em /api/openapi.json)
cd backend
cp .env.example .env
uv sync
uv run chamados db upgrade              # cria o administrador padrão: admin / admin (troca no primeiro acesso)
uv run uvicorn chamados.main:create_app --factory --reload

# em outro terminal, na raiz: CSS das telas (Tailwind), gerado de novo a cada mudança nos templates
scripts/css.sh --watch

# em outro terminal, em backend/: worker (fila de tarefas e rotinas diárias), quando precisar dele
uv run chamados worker
```

### Verificação

```bash
scripts/install-hooks.sh                # uma vez: verificação rápida antes de cada commit
scripts/check.sh                        # uma vez, antes do commit: tipos e os testes do que mudou
scripts/check.sh --completo             # antes de uma versão: todos os testes, também no PostgreSQL 16, e auditoria
```

Detalhes em [Processo de desenvolvimento](docs/12-processo-de-desenvolvimento.md#123-verificação-local-no-lugar-do-ci).

### Convenções

- Documentação em **português**; identificadores de código e banco em **inglês** (`ticket`, `comment`, `assignee`). Ver [ADR 0001](docs/adr/0001-registro-de-decisoes.md).
- Decisões relevantes viram um ADR em `docs/adr/` (status: proposta → aceita / rejeitada / substituída).
- Commits seguindo [Conventional Commits](https://www.conventionalcommits.org/pt-br/) (`feat:`, `fix:`, `docs:` …), direto na `main` do [GitHub](https://github.com/0LB-i/ticketflow); a verificação é por script na própria máquina, sem CI.

## Documentação

**Implantar e operar**
- [Manual do servidor](docs/18-manual-do-servidor.md): instalação no Ubuntu 24.04, atualização, backup, rotina e problemas comuns
- [Plano de implantação](docs/16-implantacao.md): virada da TI, treinamento, combinados, acompanhamento e expansão
- [Estrutura inicial](docs/15-estrutura-inicial.md): modelo para a carga inicial (grupos, usuários, categorias)

**Como o sistema funciona**
- [Chamados](docs/10-chamados.md): registro, status, fluxo, trabalho da equipe, aprovações, notificações
- [Organização e permissões](docs/08-organizacao-e-permissoes.md): grupos, papéis, permissões e visibilidade
- [Login e autenticação](docs/09-login-e-autenticacao.md): login por e-mail e senha, MFA, sessões
- [Anexos e arquivos](docs/11-anexos-e-arquivos.md): onde se anexa, tipos, limites, armazenamento, permissões
- [Telas e navegação](docs/13-telas-e-navegacao.md): mapa de telas, menus por perfil, padrões de interação
- [Relatórios e indicadores](docs/14-relatorios-e-indicadores.md): indicadores, painéis por perfil e exportações
- [Identidade visual](docs/17-identidade-visual.md): nome, cores, contraste, tipografia, logotipo e e-mails

**Desenvolver**
- [ARCHITECTURE.md](ARCHITECTURE.md): guia da estrutura do código
- [Arquitetura](docs/03-arquitetura.md): princípios, stack, arquitetura-alvo, implantação
- [Modelo de dados](docs/04-modelo-de-dados.md): entidades e esboço do schema PostgreSQL
- [API](docs/05-api.md): convenções REST, autenticação, endpoints
- [Processo de desenvolvimento](docs/12-processo-de-desenvolvimento.md): tarefas, commits, verificação local, definição de pronto, testes
- [ADRs](docs/adr/): registro de decisões de arquitetura
- [Glossário](docs/glossario.md): termos do domínio e nomes no código

**Projeto**
- [Visão geral](docs/01-visao-geral.md): problema, objetivos, público, escopo
- [Requisitos](docs/02-requisitos.md): requisitos funcionais e não funcionais
- [Roadmap](docs/07-roadmap.md): fases, sprints, entregas e critérios de pronto
- [Integração com IA](docs/06-integracao-ia.md): plano para depois da v1.0 (casos de uso, arquitetura, segurança e LGPD)
- [Questões em aberto](docs/questoes-em-aberto.md): decisões ainda pendentes

## Stack

- **Linguagem:** Python 3.12+
- **API:** FastAPI + Pydantic v2
- **Banco:** PostgreSQL 17 (compatível com 16); uma instalação por empresa
- **Acesso a dados:** SQLAlchemy 2.x + psycopg 3, migrações com Alembic
- **Tarefas assíncronas:** fila no próprio PostgreSQL (`SELECT ... FOR UPDATE SKIP LOCKED`)
- **Interface web:** telas renderizadas no servidor com Jinja2 + HTMX + Tailwind CSS (binário standalone, sem Node), [ADR 0011](docs/adr/0011-interface-web-no-servidor.md); editor Tiptap (Markdown). A API REST continua para integrações
- **Idiomas:** português e inglês (padrão do sistema + escolha de cada usuário)
- **Produção:** serviços systemd (uvicorn) + nginx + PostgreSQL 17 no mesmo servidor
- **IA (depois da v1.0):** uma única API genérica (formato compatível com OpenAI), configurada por URL, chave e nome do modelo, sem código específico de provedor

As justificativas estão em [docs/03-arquitetura.md](docs/03-arquitetura.md) e nos [ADRs](docs/adr/).

## Licença

[MIT](LICENSE): livre para baixar, usar, alterar e redistribuir, inclusive comercialmente, desde que se mantenha o aviso de copyright.
