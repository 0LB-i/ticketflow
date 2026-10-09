# Questões em aberto

Decisões pendentes, ordenadas pelo impacto. Quando uma for decidida, registre um ADR (se for de arquitetura) ou atualize o documento correspondente, e mova a questão para "Decididas".

## Técnicas

| # | Questão | Opções | Recomendação | Bloqueia |
|---|---------|--------|--------------|----------|
| 1 | **Servidor de e-mail para envio (SMTP)** das notificações e convites | Conta SMTP do provedor de e-mail da Martiniti, serviço transacional (ex.: Amazon SES, Brevo) | Usar a conta SMTP do provedor atual; precisamos saber qual é | Sprint 2 |
| 2 | **Servidor de produção** | Sistema operacional, recursos, domínio e certificado HTTPS | Linux (Debian/Ubuntu LTS), 2 vCPU, 4 GB RAM, 50 GB de disco bastam para 50 usuários | Sprint 5 |
| 3 | **Entrada por e-mail** (abrir chamado mandando e-mail) | IMAP no provedor de e-mail da Martiniti; ou não ter | Decidir no piloto se vale a pena para 50 pessoas | Sprint 7 |
| 4 | **Editor de texto dos comentários** | Markdown puro (textarea), Tiptap (rich text que salva Markdown) | Tiptap: colar imagens, negrito e listas sem o usuário saber Markdown | Sprint 3 |

## De negócio (dependem de quem vai usar)

| # | Questão | Padrão proposto | Onde está |
|---|---------|-----------------|-----------|
| 5 | **Etapas (status) do chamado**: a equipe ainda vai discutir | Pendente, Aguardando cliente, Entregue, Concluído, Cancelado; o admin pode criar outros | [10.5](10-chamados.md#105-status-e-fluxo) |
| 6 | **Quem pode concluir** um chamado entregue | Agente do grupo ou solicitante, sempre manualmente | 10.5 |
| 7 | Arquivos **compactados** (zip, 7z) permitidos? | Só com antivírus ativo | [11.2](11-anexos-e-arquivos.md#112-tipos-de-arquivo) |
| 8 | **Duração da sessão** | 8 h sem uso; 7 dias no máximo | [9.7](09-login-e-autenticacao.md#97-sessões) |
| 9 | **Política de retenção** de chamados concluídos, anexos e `ai_runs` | Definir com jurídico / DPO; configurável por instalação | — |
| 10 | **Licença e distribuição** do produto | Definir antes de distribuir para outras empresas | — |

Os itens 5 a 8 já têm padrão, então **não bloqueiam** o desenvolvimento.

## Decididas

| Data | Decisão | Registro |
|------|---------|----------|
| 2026-10-09 | Python + PostgreSQL 16/17 | [ADR 0002](adr/0002-python-fastapi.md), [ADR 0003](adr/0003-postgresql.md) |
| 2026-10-09 | IA por uma única API genérica (compatível com OpenAI), assistiva por padrão | [ADR 0004](adr/0004-ia-api-generica-e-assistiva.md) |
| 2026-10-09 | Uma instalação por empresa | [ADR 0005](adr/0005-instalacao-por-empresa.md) |
| 2026-10-09 | Interface: SPA em Vue 3 + TypeScript + Tailwind | [ADR 0007](adr/0007-interface-web-vue.md) |
| 2026-10-09 | Componentes: Reka UI + design system próprio em Tailwind | [ADR 0008](adr/0008-reka-ui.md) |
| 2026-10-09 | GitHub (código, Actions, Projects) | [ADR 0009](adr/0009-github.md) |
| 2026-10-09 | Produção com systemd + uvicorn + nginx, sem Docker | [ADR 0010](adr/0010-producao-systemd.md) |
| 2026-10-09 | Login só por e-mail e senha (sem diretório de contas); SSO para o futuro | [09](09-login-e-autenticacao.md) |
| 2026-10-09 | Anexos em disco local | [11.6](11-anexos-e-arquivos.md#116-armazenamento) |
| 2026-10-09 | Até 50 usuários | [02](02-requisitos.md) |
| 2026-10-09 | Modelo de organização: setores, grupos de atendimento, papéis e permissões | [08](08-organizacao-e-permissoes.md) |
| 2026-10-09 | Fluxo de chamados, login e anexos | [09](09-login-e-autenticacao.md), [10](10-chamados.md), [11](11-anexos-e-arquivos.md) |
| 2026-10-09 | Agentes veem e trabalham só os chamados dos **próprios grupos** | [8.4](08-organizacao-e-permissoes.md#84-regras-de-visibilidade-de-chamados) |
| 2026-10-09 | **Sem SLA**: sem metas de prazo, alertas nem calendário de expediente | [10.9](10-chamados.md#109-prazos-sem-sla) |
| 2026-10-09 | **Nada fecha sozinho**: concluir é sempre manual; não há resolução por falta de retorno | [10.5](10-chamados.md#105-status-e-fluxo) |
| 2026-10-09 | **Sem etapa de fornecedor/terceiro**: o atendimento é todo interno (Martiniti) | [01](01-visao-geral.md#público) |
