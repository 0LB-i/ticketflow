# Questões em aberto

Decisões pendentes, ordenadas pelo impacto. Quando uma for decidida, registre um ADR (se for de arquitetura) ou atualize o documento correspondente, e mova a questão para "Decididas".

## Técnicas

| # | Questão | Opções | Recomendação | Bloqueia |
|---|---------|--------|--------------|----------|
| 1 | **Armazenamento de anexos** | Disco local, S3-compatível | Local como padrão + S3 opcional, atrás da mesma interface ([11.6](11-anexos-e-arquivos.md#116-armazenamento)) | Sprint 4 |
| 2 | **Provedor de identidade** | Entra ID, Google Workspace, Keycloak | OIDC genérico cobre os três | Sprint 7 |
| 3 | **Entrada por e-mail** | IMAP genérico, Microsoft Graph, Gmail API | IMAP primeiro; Graph se a empresa usar M365 com IMAP desativado | Sprint 8 |
| 4 | **Editor de texto dos comentários** | Markdown puro (textarea), Tiptap (rich text que salva Markdown) | Tiptap: colar imagens, negrito e listas sem o usuário saber Markdown | Sprint 3 |

## De negócio (dependem de quem vai usar)

| # | Questão | Padrão proposto | Onde está |
|---|---------|-----------------|-----------|
| 5 | Agentes veem chamados de **outros grupos**? | Não | [8.3](08-organizacao-e-permissoes.md#83-catálogo-de-permissões) |
| 6 | Dias úteis até **fechar automaticamente** um chamado resolvido | 3 | [10.5](10-chamados.md#105-status-e-fluxo) |
| 7 | Dias úteis sem resposta do solicitante até **resolver por falta de retorno** | 5 (lembrete no 2º) | 10.5 |
| 8 | "Aguardando terceiro" **pausa o SLA**? | Não | 10.5 |
| 9 | **Metas de SLA** por prioridade | Tabela em [10.9](10-chamados.md#109-sla-fase-2) | 10.9 |
| 10 | Arquivos **compactados** (zip, 7z) permitidos? | Só com antivírus ativo | [11.2](11-anexos-e-arquivos.md#112-tipos-de-arquivo) |
| 11 | **Duração da sessão** | 8 h sem uso; 7 dias no máximo | [9.7](09-login-e-autenticacao.md#97-sessões) |
| 12 | **Política de retenção** de chamados fechados, anexos e `ai_runs` | Definir com jurídico / DPO; configurável por instalação | — |
| 13 | **Licença e distribuição** do produto | Definir antes de distribuir para outras empresas | — |

Os itens 5 a 11 já têm padrão e são configuráveis, então **não bloqueiam** o desenvolvimento. Precisam só ser validados com a área piloto.

## Decididas

| Data | Decisão | Registro |
|------|---------|----------|
| 2026-10-09 | Python + PostgreSQL 16/17 | [ADR 0002](adr/0002-python-fastapi.md), [ADR 0003](adr/0003-postgresql.md) |
| 2026-10-09 | IA por uma única API genérica (compatível com OpenAI), assistiva por padrão | [ADR 0004](adr/0004-ia-api-generica-e-assistiva.md) |
| 2026-10-09 | Uma instalação por empresa | [ADR 0005](adr/0005-instalacao-por-empresa.md) |
| 2026-10-09 | Interface: SPA em Vue 3 + TypeScript + Tailwind | [ADR 0007](adr/0007-interface-web-vue.md) |
| 2026-10-09 | Componentes: Reka UI + design system próprio em Tailwind | [ADR 0008](adr/0008-reka-ui.md) |
| 2026-10-09 | GitHub (código, Actions, Projects, GHCR) | [ADR 0009](adr/0009-github.md) |
| 2026-10-09 | Modelo de organização: setores, grupos de atendimento, papéis e permissões | [08](08-organizacao-e-permissoes.md) |
| 2026-10-09 | Fluxo de chamados, login e anexos | [09](09-login-e-autenticacao.md), [10](10-chamados.md), [11](11-anexos-e-arquivos.md) |
