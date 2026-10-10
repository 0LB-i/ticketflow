# Questões em aberto

Decisões pendentes, ordenadas pelo impacto. Quando uma for decidida, registre um ADR (se for de arquitetura) ou atualize o documento correspondente, e mova a questão para "Decididas".

## Técnicas

| # | Questão | Opções | Recomendação | Bloqueia |
|---|---------|--------|--------------|----------|
| 1 | **Servidor de e-mail para envio (SMTP)** das notificações e convites | Conta SMTP do provedor de e-mail da empresa, serviço transacional (ex.: Amazon SES, Brevo) | Usar a conta SMTP do provedor atual; precisamos saber qual é. Até lá, o admin copia os links de convite e redefinição na tela de usuários ([9.4](09-login-e-autenticacao.md#94-convite-esqueci-a-senha-e-troca-de-senha)) | Sprint 4 (notificações de chamados) |
| 2 | **Servidor de produção**: domínio e certificado HTTPS (o sistema operacional já foi decidido) | Let's Encrypt, Let's Encrypt por DNS ou certificado da empresa ([18.2](18-manual-do-servidor.md#182-requisitos)) | 2 vCPU, 4 GB RAM, 50 GB de disco; nome `ticketflow.example.com` | Sprint 5 |
| 13 | **Destino da cópia externa do backup** | Outro servidor, NAS da empresa, armazenamento em nuvem | O que a TI já usar para os outros backups ([18.5](18-manual-do-servidor.md#185-backup-e-restauração)) | Sprint 5 |

## De negócio (dependem de quem vai usar)

| # | Questão | Padrão proposto | Onde está |
|---|---------|-----------------|-----------|
| 5 | **Etapas (status) e tipos do chamado**: a equipe ainda vai discutir | Status: Pendente, Aguardando, Concluído, Cancelado. Tipos: incidente, requisição, tarefa. O admin pode criar outros status | [10.5](10-chamados.md#105-status-e-fluxo) |
| 6 | **Quem pode concluir** um chamado | Responsável ou supervisor do grupo, sempre manualmente | 10.5 |
| 7 | Arquivos **compactados** (zip, 7z) permitidos? | Bloqueados na v1.0 (sem antivírus); o admin pode liberar | [11.2](11-anexos-e-arquivos.md#112-tipos-de-arquivo) |
| 8 | **Duração da sessão** | 8 h sem uso; 7 dias no máximo | [9.7](09-login-e-autenticacao.md#97-sessões) |
| 9 | **Política de retenção** de chamados concluídos e anexos | Definir com jurídico / DPO; configurável por instalação | — |
| 10 | **Licença e distribuição** do produto | Definir antes de distribuir para outras empresas | — |

| 11 | **Código hex oficial do laranja** da empresa | Escala `orange` do Tailwind até chegar o oficial; quando chegar, o admin digita em Configurações | [17.2](17-identidade-visual.md#172-cores) |
| 12 | **Data da virada** da TI | Terça ou quarta-feira no fim da Sprint 5, fora de fechamento de mês | [16.3](16-implantacao.md#163-cronograma) |

Os itens 5 a 8, 11 e 12 já têm padrão, então **não bloqueiam** o desenvolvimento.

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
| 2026-10-09 | **Revisão de escopo**: IA, tokens de API, webhooks, MCP, papéis personalizados, visões salvas, atalhos, antivírus e campos extras ficam para depois da v1.0; v1.0 em 16 semanas | [07](07-roadmap.md#backlog-futuro-fora-da-v10) |
| 2026-10-10 | **Modelo**: ferramenta de trabalho das equipes; só membros têm conta; colegas acompanham como observadores; chamado registra setor e pessoa atendidos; supervisor aprova | [08](08-organizacao-e-permissoes.md), [10](10-chamados.md) |
| 2026-10-10 | Nome **TicketFlow**; cores laranja, cinza e branco | [17](17-identidade-visual.md) |
| 2026-10-10 | **Repositório Git local** por enquanto; GitHub quando houver remoto. Verificação por `scripts/check.sh`, tarefas em `TAREFAS.md` | [12](12-processo-de-desenvolvimento.md), [ADR 0009](adr/0009-github.md) |
| 2026-10-10 | Servidor de produção em **Ubuntu 24.04 LTS**; código entregue por repositório Git de passagem no servidor; sem homologação | [18](18-manual-do-servidor.md) |
| 2026-10-10 | **Uma pessoa** desenvolve, com o Claude Code; roadmap reestimado para 20 a 27 semanas | [07](07-roadmap.md) |
| 2026-10-10 | Mapeamento de grupos do SSO sai do schema da v1.0 | [`esboco-schema-futuro.sql`](esboco-schema-futuro.sql) |
| 2026-10-10 | Senha com **mínimo de 8 caracteres**; **administrador padrão `admin`/`admin`** com troca obrigatória no primeiro acesso; login por e-mail ou usuário | [9.2](09-login-e-autenticacao.md#92-primeiro-acesso-à-instalação), [9.3](09-login-e-autenticacao.md#93-login-local) |
| 2026-10-10 | **Virada com data marcada** no piloto da TI; sem importação de histórico | [16](16-implantacao.md) |
| 2026-10-10 | **Configurações** para o admin: idioma padrão (português e inglês, e cada usuário escolhe o seu), as 3 cores com ajuste automático de contraste, e logotipo | [13](13-telas-e-navegacao.md#133-lista-de-telas), [17](17-identidade-visual.md#172-cores) |
| 2026-10-10 | **Editor Tiptap** na descrição e nos comentários, gravando Markdown | [05](05-api.md#chamados) |
| 2026-10-09 | **Sem etapa de fornecedor/terceiro**: o atendimento é todo interno (empresa) | [01](01-visao-geral.md#público) |
