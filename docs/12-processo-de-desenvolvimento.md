# 12. Processo de desenvolvimento

> **Situação atual (2026-10-10):** uma pessoa desenvolve, com o Claude Code, num **repositório Git local**. O GitHub ([ADR 0009](adr/0009-github.md)) fica para quando houver um remoto; até lá, o que ele faria (CI, issues, quadro) é feito por scripts e arquivos no próprio repositório. A seção 12.8 guarda o plano do GitHub.

## 12.1 Repositório e tarefas

- **Repositório:** Git local, monorepo `backend/` + `frontend/` + `docs/`. Uma cópia fica no repositório de passagem do servidor de produção ([18.3](18-manual-do-servidor.md#5-código)), que também serve de cópia de segurança do código.
- **Tarefas:** arquivo `TAREFAS.md` na raiz, criado na Fase 0. Uma linha por item do [roadmap](07-roadmap.md), com o código, o estado (`a fazer`, `fazendo`, `feito`) e o commit que concluiu. Bugs e pedidos do piloto entram numa seção própria, com data e quem relatou.
- **Decisões:** continuam como ADR em `docs/adr/` e nas [questões em aberto](questoes-em-aberto.md).

### Modelo de tarefa

Cada item do roadmap é detalhado assim antes de começar, no próprio `TAREFAS.md` ou no documento de referência:

```markdown
**Como** membro da TI – Suporte
**quero** transferir um chamado para outro grupo informando o motivo
**para** que a equipe certa atenda sem perder o histórico

### Critérios de aceite
- [ ] Só membros do grupo atual (ou admin) podem transferir
- [ ] Motivo obrigatório, registrado como comentário
- [ ] Chamado continua "Pendente" no grupo de destino, sem responsável
- [ ] Grupo anterior mantém acesso somente leitura
- [ ] Evento `ticket.transferred` no histórico e no outbox

### Referências
docs/10-chamados.md#transferência
```

## 12.2 Commits

- **Todos os commits vão direto para a `main`**, sem branches de feature ou de correção (regra do [CLAUDE.md](../CLAUDE.md)).
- Commits pequenos e frequentes, no padrão Conventional Commits (`feat(chamados): transferir entre grupos`), citando o código do roadmap quando houver.
- A verificação rápida roda antes de cada commit (12.3). **Verificação completa falhando na `main` é prioridade:** corrige-se antes de continuar.

## 12.3 Verificação local (no lugar do CI)

| Quando | Comando | O que roda |
|--------|---------|------------|
| Antes de cada commit (hook `pre-commit`, instalado por `scripts/install-hooks.sh`) | `scripts/check.sh --rapido` | `ruff check`, `ruff format --check`, ESLint e Prettier nos arquivos alterados |
| Antes de marcar uma tarefa como feita e antes de cada `git push producao` | `scripts/check.sh` | Tudo do rápido + `mypy`, `pytest` com cobertura no PostgreSQL 17 (porta 5432), `vue-tsc`, Vitest, `vite build` e a verificação do contrato (OpenAPI e cliente TypeScript sem diferença não commitada) |
| Antes de cada versão (tag) | `scripts/check.sh --completo` | Tudo acima + `pytest` também no **PostgreSQL 16**, Playwright e auditoria de dependências (`pip-audit`, `pnpm audit`) |

- O `check.sh` para com uma mensagem clara se o PostgreSQL não estiver respondendo.
- **Dependências:** sem Dependabot, a atualização é uma rotina mensal registrada no `TAREFAS.md`: `uv lock --upgrade`, `pnpm update`, verificação completa e commit.
- **Segredos:** `.env` e chaves nunca entram no repositório (`.gitignore`); o `check.sh` falha se encontrar padrões de chave nos arquivos alterados.

## 12.4 Definição de pronto

Uma tarefa só fica `feito` quando:

- [ ] Critérios de aceite atendidos
- [ ] Testes automatizados: unitários e de integração (backend com banco real); componente ou ponta a ponta (frontend), quando aplicável
- [ ] **Testes de permissão** para qualquer endpoint novo ou alterado
- [ ] Migração Alembic reversível (`downgrade`) e compatível com a versão anterior da aplicação
- [ ] OpenAPI atualizada e cliente TypeScript regenerado
- [ ] Textos da interface no i18n, em português **e** inglês, sem texto fixo no código; mensagens de erro novas da API no catálogo de `core/i18n.py`
- [ ] Acessibilidade verificada: navegação por teclado, foco visível, rótulos
- [ ] Documentação em `docs/` atualizada quando a regra de negócio mudou; [ARCHITECTURE.md](../ARCHITECTURE.md) atualizado quando a estrutura mudou (módulo, camada ou regra nova)
- [ ] **Revisão:** sem um segundo desenvolvedor, a mudança passa pelo `/code-review` do Claude Code; mudanças em login, permissões ou anexos passam também pelo `/security-review`
- [ ] `scripts/check.sh` passando

## 12.5 Versões e entregas

- **SemVer:** `MAJOR.MINOR.PATCH`. MAJOR exige um passo manual na atualização; MINOR traz funcionalidades; PATCH, correções.
- Cada versão é uma **tag** na `main` e traz **notas de atualização** em `CHANGELOG.md`, geradas a partir dos commits: migrações, novas variáveis de ambiente, mudanças de comportamento.
- A atualização no servidor segue o [manual do servidor](18-manual-do-servidor.md#184-atualização). Quem reinicia os serviços é o usuário ([ADR 0010](adr/0010-producao-systemd.md)).
- Versões `0.x` até o M2; `1.0.0` ao fim da Fase 2 (M2).

## 12.6 Ambientes

| Ambiente | Para quê |
|----------|----------|
| **Local** | Desenvolvimento: PostgreSQL 17 e 16 nativos (`scripts/preparar-maquina-dev.sh` prepara uma máquina nova) + `uvicorn --reload` + `pnpm dev`, ou o serviço systemd local (`scripts/instalar-servico-dev.sh`). Também é onde roda a verificação (12.3) e, quando existir, a demonstração com `chamados dev seed` |
| **Produção** | Servidor da empresa, com serviços systemd, atualizado pelo script de deploy ([18](18-manual-do-servidor.md)) |

Não há homologação separada: com um único desenvolvedor, mais um servidor seria mais trabalho de manutenção do que ganho. O treinamento da equipe é feito na própria produção, antes da virada, num grupo **Treinamento** que é desativado depois ([16.5](16-implantacao.md#165-treinamento-1-hora)). Se o sistema for instalado em outras empresas, a homologação volta a ser avaliada.

## 12.7 Estratégia de testes

| Nível | Ferramenta | Cobre |
|-------|------------|-------|
| Unitário (backend) | pytest | Regras puras: matriz de prioridade, transições |
| Integração (backend) | pytest + PostgreSQL real (banco `chamados_test`) | Services e endpoints com PostgreSQL real |
| Permissões | pytest parametrizado | Matriz perfil × ação × situação do chamado ([08](08-organizacao-e-permissoes.md)) |
| Componentes (frontend) | Vitest + Vue Test Utils | Componentes e composables |
| Ponta a ponta | Playwright | Fluxos completos: registrar → assumir → aguardar → concluir → reabrir; aprovação; transferência |

**Dados de teste:** *factories* (factory-boy) no backend e um comando `chamados dev seed`, que cria uma empresa fictícia com grupos, setores atendidos, usuários de todos os perfis e chamados em todos os status.

## 12.8 Quando houver remoto no GitHub (plano guardado)

Ao criar o remoto, o que hoje é local passa para o GitHub, sem mudar o resto do processo:

| Hoje (local) | No GitHub |
|--------------|-----------|
| `TAREFAS.md` | Issues com o código do roadmap no título (ex.: `[F1-S3-07] Transferir chamado entre grupos`), milestones por fase e GitHub Projects (*Backlog → Pronto para desenvolver → Em andamento → Concluído*) |
| `scripts/check.sh` | GitHub Actions: `backend.yml` (matriz PostgreSQL 16 e 17), `frontend.yml`, `contract.yml`, `e2e.yml` (Playwright) e `codeql.yml` |
| Rotina mensal de dependências | Dependabot (uv, pnpm, Actions), secret scanning e push protection |
| Tag + `CHANGELOG.md` | `release.yml` gerando a release a partir da tag |
| Repositório de passagem no servidor | O servidor busca do GitHub |

Os workflows chamam o mesmo `scripts/check.sh`, para que a verificação local e a do CI sejam idênticas.
