# Tarefas

Andamento dos itens do [roadmap](docs/07-roadmap.md). Estados: `a fazer`, `fazendo`, `feito` ([docs/12 §12.1](docs/12-processo-de-desenvolvimento.md#121-repositório-e-tarefas)).
Ao concluir um item, marque `feito` e anote o commit.

## Fase 0 — Fundação (Sprint 1)

| Código | Entrega | Estado | Commit |
|--------|---------|--------|--------|
| F0-01 | Repositório local: `TAREFAS.md` com os itens deste roadmap, `CHANGELOG.md`, `.gitignore` ([12.1](docs/12-processo-de-desenvolvimento.md#121-repositório-e-tarefas)) | feito | 75d07b7 |
| F0-02 | Monorepo `backend/` + `frontend/`; README com "como rodar" | feito | 75d07b7 |
| F0-03 | Backend: `pyproject.toml` (uv), FastAPI com `/health`, configuração com pydantic-settings, logs estruturados (structlog), tratamento de erros (RFC 9457) | feito | e163d3c |
| F0-04 | Banco: SQLAlchemy 2 + Alembic; migração inicial com extensões (`unaccent`, `pg_trgm`, `citext`) e a configuração de busca `pt_br` | feito | e163d3c |
| F0-05 | Frontend: Vue 3 + TypeScript + Vite + Tailwind + Reka UI; Vue Router, Pinia, TanStack Query, vue-i18n | feito | 75d07b7 |
| F0-06 | Design system inicial conforme a [identidade visual](docs/17-identidade-visual.md): cores, tipografia, espaçamento (tokens do Tailwind), modo claro e escuro; componentes base: Botão, Campo, Select, Modal, Toast, Tabela, Badge de status | feito | 75d07b7 |
| F0-07 | Layout do aplicativo: menu lateral, cabeçalho, área de conteúdo, responsivo | feito | 75d07b7 |
| F0-08 | Geração do cliente TypeScript a partir do OpenAPI (`pnpm gen:api`) + verificação do contrato no `scripts/check.sh` | feito | 75d07b7 |
| F0-09 | `docker-compose.yml` só para desenvolvimento (PostgreSQL 17, Mailpit); arquivos do systemd (serviços e timer de backup) e do nginx; `scripts/deploy.sh` e `scripts/backup.sh` ([18](docs/18-manual-do-servidor.md)) | feito | 75d07b7 |
| F0-10 | `scripts/check.sh` (rápido, padrão e completo, com testes em **PG 16 e 17**) e hook de pre-commit ([12.3](docs/12-processo-de-desenvolvimento.md#123-verificação-local-no-lugar-do-ci)) | feito | 75d07b7 |

## Fase 1 — MVP (Sprints 2 a 5)

### Sprint 2 — Identidade e organização

| Código | Entrega | Estado | Commit |
|--------|---------|--------|--------|
| F1-S2-01 | Login local, sessões no servidor, CSRF, logout | a fazer | |
| F1-S2-02 | Comando `chamados admin create`; convite e "esqueci a senha" por e-mail | a fazer | |
| F1-S2-03 | Proteção contra força bruta (rate limit + bloqueio temporário) | a fazer | |
| F1-S2-04 | Cadastro de **setores atendidos** (árvore) | a fazer | |
| F1-S2-05 | Cadastro de **grupos** (membros + supervisores) | a fazer | |
| F1-S2-06 | Cadastro de **usuários** (papel, grupos) com convite por e-mail | a fazer | |
| F1-S2-07 | **Motor de permissões**: catálogo, papéis fixos, `can()` e `ticket_visibility_filter()` + testes tabelados | a fazer | |
| F1-S2-08 | Log de auditoria (`audit_log`) para login e administração | a fazer | |
| F1-S2-09 | Telas: login, redefinição de senha, administração de usuários, grupos e setores | a fazer | |

### Sprint 3 — Núcleo dos chamados

| Código | Entrega | Estado | Commit |
|--------|---------|--------|--------|
| F1-S3-01 | Cadastro de **categorias** (árvore, grupo padrão, tipo padrão, confidencial) | a fazer | |
| F1-S3-02 | Status padrão e **motor de transições** (quem pode, campos exigidos) | a fazer | |
| F1-S3-03 | **Registro** de chamado: formulário, setor e pessoa atendidos, responsável na criação, matriz impacto × urgência | a fazer | |
| F1-S3-04 | **Observadores** e @menções | a fazer | |
| F1-S3-05 | Roteamento por categoria → grupo | a fazer | |
| F1-S3-06 | **Comentários**; edição em 10 min | a fazer | |
| F1-S3-07 | Assumir, atribuir, **transferir** (com motivo) | a fazer | |
| F1-S3-08 | **Histórico** (`ticket_events`) e linha do tempo | a fazer | |
| F1-S3-09 | Telas: novo chamado e detalhe do chamado | a fazer | |

### Sprint 4 — Anexos, notificações, filas e busca

| Código | Entrega | Estado | Commit |
|--------|---------|--------|--------|
| F1-S4-01 | **Upload em duas etapas**, validação de tipo e tamanho, armazenamento local | a fazer | |
| F1-S4-02 | Download com verificação de permissão; imagens coladas no editor | a fazer | |
| F1-S4-03 | **Outbox + worker + fila de tarefas** no PostgreSQL | a fazer | |
| F1-S4-04 | **Notificações por e-mail** (templates em pt-BR) | a fazer | |
| F1-S4-05 | **Filas**: não atribuídos, meus chamados, com novidades, aguardando, acompanhando, todos do grupo | a fazer | |
| F1-S4-06 | Botão "Pegar o próximo" | a fazer | |
| F1-S4-07 | **Busca textual** em português + filtros | a fazer | |
| F1-S4-08 | Indicador de colisão ("Fulano está vendo") + `ETag` | a fazer | |

### Sprint 5 — Ciclo completo e preparação do piloto

| Código | Entrega | Estado | Commit |
|--------|---------|--------|--------|
| F1-S5-01 | Aguardar, concluir (texto + código), **reabrir**, cancelar | a fazer | |
| F1-S5-02 | Status personalizados criados pelo administrador (com `kind`) | a fazer | |
| F1-S5-03 | Ocultar comentário ou anexo com motivo | a fazer | |
| F1-S5-04 | Testes ponta a ponta (Playwright) dos fluxos principais | a fazer | |
| F1-S5-05 | Revisão de segurança (OWASP ASVS nível 2, itens aplicáveis) e de acessibilidade | a fazer | |
| F1-S5-06 | Instalação no servidor da Martiniti (systemd, nginx, PostgreSQL 17), backup testado com restauração | a fazer | |
| F1-S5-07 | Carga inicial da Martiniti: grupos, usuários, setores atendidos, categorias | a fazer | |
| F1-S5-08 | Treinamento, guia rápido e virada da TI | a fazer | |

## Fase 2 — Operação completa (Sprints 6 a 8)

### Sprint 6 — Notificações, MFA e aprovações

| Código | Entrega | Estado | Commit |
|--------|---------|--------|--------|
| F2-S6-01 | Notificações no sistema (sino) + preferências de notificação | a fazer | |
| F2-S6-02 | MFA por TOTP + códigos de recuperação; obrigatório para administradores | a fazer | |
| F2-S6-03 | Gerenciamento de sessões pelo usuário e pelo admin | a fazer | |
| F2-S6-04 | **Aprovações** pelo supervisor do grupo, lembretes | a fazer | |

### Sprint 7 — Enriquecimento dos chamados e conhecimento

| Código | Entrega | Estado | Commit |
|--------|---------|--------|--------|
| F2-S7-01 | Vínculos e **mesclagem** de duplicados | a fazer | |
| F2-S7-02 | Ações em massa | a fazer | |
| F2-S7-03 | Gestão de membros do grupo pelo supervisor | a fazer | |
| F2-S7-04 | Base de conhecimento da equipe (artigos, busca, artigo a partir de um chamado concluído) | a fazer | |

### Sprint 8 — Relatórios e versão 1.0

| Código | Entrega | Estado | Commit |
|--------|---------|--------|--------|
| F2-S8-01 | Painéis e relatórios conforme [14](docs/14-relatorios-e-indicadores.md); exportação CSV | a fazer | |
| F2-S8-02 | Implantação nas outras equipes ([16.10](docs/16-implantacao.md#1610-expansão-para-outras-equipes-fase-2-m2)) | a fazer | |
| F2-S8-03 | Preparação da v1.0: testes ponta a ponta completos, revisão de segurança, guia do administrador | a fazer | |

## Rotinas

| Rotina | Frequência | Última vez |
|--------|------------|------------|
| Atualizar dependências (`uv lock --upgrade`, `pnpm update`) + `scripts/check.sh --completo` | Mensal | |
| Testar a restauração do backup em produção ([docs/18 §18.5](docs/18-manual-do-servidor.md#185-backup-e-restauração)) | Trimestral | |

## Bugs e pedidos do piloto

| Data | Quem relatou | Descrição | Estado |
|------|--------------|-----------|--------|
