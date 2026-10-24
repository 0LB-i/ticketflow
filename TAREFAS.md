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
| F1-S2-01 | Login local, sessões no servidor, CSRF, logout | feito | 933cc3d |
| F1-S2-02 | Comando `chamados admin create`; convite e "esqueci a senha" por e-mail | feito | 933cc3d |
| F1-S2-03 | Proteção contra força bruta (rate limit + bloqueio temporário) | feito | 933cc3d |
| F1-S2-04 | Cadastro de **setores atendidos** (árvore) | feito | 933cc3d |
| F1-S2-05 | Cadastro de **grupos** (membros + supervisores) | feito | 933cc3d |
| F1-S2-06 | Cadastro de **usuários** (papel, grupos) com convite por e-mail | feito | 933cc3d |
| F1-S2-07 | **Motor de permissões**: catálogo, papéis fixos, `can()` e `ticket_visibility_filter()` + testes tabelados | feito | 933cc3d |
| F1-S2-08 | Log de auditoria (`audit_log`) para login e administração | feito | 933cc3d |
| F1-S2-09 | Telas: login, redefinição de senha, administração de usuários, grupos e setores | feito | 415d0c2 |

### Sprint 3 — Núcleo dos chamados

| Código | Entrega | Estado | Commit |
|--------|---------|--------|--------|
| F1-S3-01 | Cadastro de **categorias** (árvore, grupo padrão, tipo padrão, confidencial) | feito | f0d0413, 6a563ad |
| F1-S3-02 | Status padrão e **motor de transições** (quem pode, campos exigidos) | feito | f0d0413, 6a563ad |
| F1-S3-03 | **Registro** de chamado: formulário, setor e pessoa atendidos, responsável na criação, matriz impacto × urgência | feito | f0d0413, 6a563ad |
| F1-S3-04 | **Observadores** e @menções | feito | f0d0413, 6a563ad |
| F1-S3-05 | Roteamento por categoria → grupo | feito | f0d0413, 6a563ad |
| F1-S3-06 | **Comentários**; edição em 10 min | feito | f0d0413, 6a563ad |
| F1-S3-07 | Assumir, atribuir, **transferir** (com motivo) | feito | f0d0413, 6a563ad |
| F1-S3-08 | **Histórico** (`ticket_events`) e linha do tempo | feito | f0d0413, 6a563ad |
| F1-S3-09 | Telas: novo chamado e detalhe do chamado | feito | 6a563ad |
| F1-S3-10 | `ticket_visibility_filter()` + testes tabelados das regras de visibilidade (saiu da S2-07) | feito | f0d0413 |
| F1-S3-11 | Configurações: idioma (pt-BR/en, padrão + usuário), 3 cores com ajuste de contraste, logotipo | feito | 4d5a338, fac38c2 |

### Sprint 4 — Anexos, notificações, filas e busca

| Código | Entrega | Estado | Commit |
|--------|---------|--------|--------|
| F1-S4-01 | **Upload em duas etapas**, validação de tipo e tamanho, armazenamento local | feito | e7d0f2a |
| F1-S4-02 | Download com verificação de permissão; imagens coladas no editor | feito | e7d0f2a |
| F1-S4-03 | **Outbox + worker + fila de tarefas** no PostgreSQL (fila própria; limpeza dos anexos vira rotina diária) | feito | fc6bcd6 |
| F1-S4-04 | **Notificações por e-mail** (templates em pt-BR e en; Mailpit no desenvolvimento) | feito | 46e31b9 |
| F1-S4-05 | **Filas**: meus chamados, aguardando, acompanhando, todos do grupo | feito | d7dc992 |
| F1-S4-06 | Botão "Pegar o próximo" | removido em 2026-10-15 (todo chamado tem responsável) | d7dc992 |
| F1-S4-07 | **Busca textual** em português + filtros | feito | d7dc992 |
| F1-S4-08 | Indicador de colisão ("Fulano está vendo") + `ETag` | feito | e519604 |

### Sprint 5 — Ciclo completo e preparação do piloto

| Código | Entrega | Estado | Commit |
|--------|---------|--------|--------|
| F1-S5-01 | Aguardar, concluir (texto + código), **reabrir**, cancelar | feito | f0d0413, 6a563ad |
| F1-S5-02 | Status personalizados criados pelo administrador (com `kind`); fica em Configurações, códigos de resolução personalizados continuam pendentes | feito | |
| F1-S5-03 | Ocultar comentário ou anexo com motivo | a fazer | |
| F1-S5-04 | Testes ponta a ponta (Playwright) dos fluxos principais | a fazer | |
| F1-S5-05 | Revisão de segurança (OWASP ASVS nível 2, itens aplicáveis) e de acessibilidade | a fazer | |
| F1-S5-06 | Instalação no servidor da empresa (systemd, nginx, PostgreSQL 17) | a fazer | |
| F1-S5-07 | Carga inicial da empresa: grupos, usuários, setores atendidos, categorias | a fazer | |
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
| F2-S8-00 | Relatórios de horas: produtividade, clientes, horas extras (expediente) e PDF ([14.7](docs/14-relatorios-e-indicadores.md#147-relatórios-de-horas-pedido-do-usuário-2026-10-15)); pedido do usuário, antecipado | feito | |
| F2-S8-01 | Painéis por perfil ([14.4](docs/14-relatorios-e-indicadores.md#144-painéis-por-perfil)) como modelos prontos e o relatório de transferências; os indicadores e o CSV entram pela F2-S8-04 a 06 | a fazer | |
| F2-S8-02 | Implantação nas outras equipes ([16.10](docs/16-implantacao.md#1610-expansão-para-outras-equipes-fase-2-m2)) | a fazer | |
| F2-S8-03 | Preparação da v1.0: testes ponta a ponta completos, revisão de segurança, guia do administrador | a fazer | |
| F2-S8-04 | Relatórios, fase 1 ([14.8](docs/14-relatorios-e-indicadores.md#148-relatórios-personalizados-pedido-do-usuário-2026-10-24)): CSV das telas atuais, períodos relativos, filtros com vários valores | feito | |
| F2-S8-05 | Relatórios, fase 2: construtor guiado (medidas de tarefas, registrados e concluídos), modelos pessoais salvos, modelos prontos, modelo inicial, CSV de cada bloco | feito | |
| F2-S8-06 | Relatórios, fase 3: medidas de chamados (§14.3), modelo pronto Chamados, idade do em aberto, colunas empilhadas, comparação com o período anterior, detalhar ao clicar (com a lista de chamados) | feito | |
| F2-S8-07 | Relatórios, fase 4: PDF do modelo com gráficos e relatório para o cliente | feito | |

## Migração da interface para o servidor ([ADR 0011](docs/adr/0011-interface-web-no-servidor.md))

Concluída em 2026-10-19: todas as telas são do servidor ([ARCHITECTURE 3.11](ARCHITECTURE.md#311-telas-do-servidor-web-adr-0011)), e a SPA, o Node e o serviço do Vite saíram. Histórico e pendências: [docs/19](docs/19-migracao-da-interface.md).

| Código | Entrega | Estado | Commit |
|--------|---------|--------|--------|
| WEB-01 | Base (Jinja2, HTMX, Tailwind standalone, tema, cores personalizadas) e as telas de login, senha esquecida, convite, redefinição e troca obrigatória de senha | feito | 73010c3 |
| WEB-02 | Layout com menu lateral, cabeçalho (novo chamado, busca), menu do usuário (idioma, sair) e a lista de chamados com as filas | feito | 87a4244 |
| WEB-03 | Novo chamado e detalhe do chamado (linha do tempo, tarefas com o Tiptap empacotado, anexos, status, responsáveis) | feito | bd1614a |
| WEB-04 | Administração: usuários, grupos, setores, clientes e configurações | feito | 073b0f2, 4a89058, a041d99, a5776a9 |
| WEB-05 | Relatórios (gráficos em SVG e o PDF) | feito | b6c5e5a, 019a6cc |
| WEB-06 | Troca final: o nginx de desenvolvimento manda tudo ao uvicorn; saem o `frontend/`, o serviço do Vite e o pnpm do `check.sh` e do deploy; os catálogos de idioma passam para `web/locales/` | feito | 7dfc04c |

## Desempenho (RNF-01)

Meta do [docs/02](docs/02-requisitos.md#requisitos-não-funcionais): p95 < 300 ms nas leituras com 50 mil chamados. Medido pelo benchmark ([ARCHITECTURE 7.1](ARCHITECTURE.md#71-benchmark-backendbench)): `cd backend && uv run python -m bench`.

| Código | Entrega | Estado | Commit |
|--------|---------|--------|--------|
| DES-01 | Benchmark (`backend/bench/`): massa de 50 mil chamados, 33 cenários com meta de tempo e conferência do resultado | feito | 9454088 |
| DES-02 | Sem JIT nas conexões do app: listas, buscas, contadores e quadro passavam de 1 s só compilando a consulta ([ADR 0012](docs/adr/0012-postgresql-sem-jit.md)) | feito | |
| DES-03 | Índice `tickets(created_at, id)` para a ordem da lista (migração 0037) | feito | |
| DES-04 | PDF do relatório do mês (~5,4 s, meta de 2 s), relatório de 12 meses (~3 s), relatório do mês do admin (~530 ms), a tela Relatórios (~800 ms) e o Quadro do supervisor (p95 ~400 ms, p50 ~180 ms): achar onde vai o tempo (consultas, cálculo das horas fora do expediente, ReportLab, montagem dos cartões) | a fazer | |
| DES-05 | Vários workers na API (`--workers 4` para 8 núcleos): a presença no chamado e o limite de login por IP saem da memória para o banco (migração 0038); teste de carga com 5 pessoas (`python -m bench.carga`) | feito | |

## Rotinas

| Rotina | Frequência | Última vez |
|--------|------------|------------|
| Atualizar dependências (`uv lock --upgrade`) + `scripts/check.sh --completo` | Mensal | |

## Bugs e pedidos do piloto

| Data | Quem relatou | Descrição | Estado |
|------|--------------|-----------|--------|
