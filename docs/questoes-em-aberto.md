# Questões em aberto

Decisões pendentes, ordenadas pelo impacto. Quando uma for decidida, registre um ADR e mova a questão para "Decididas".

| # | Questão | Opções | Recomendação inicial | Bloqueia |
|---|---------|--------|----------------------|----------|
| 1 | **Armazenamento de anexos** | Disco local / volume, S3-compatível (MinIO, AWS, Azure Blob) | Interface de armazenamento com os dois adaptadores; S3 em produção | Fase 1 |
| 2 | **Provedor de identidade** | Entra ID, Google Workspace, Keycloak, LDAP | OIDC genérico cobre os três primeiros | Fase 2 |
| 3 | **Entrada por e-mail** | IMAP genérico, Microsoft Graph, Gmail API | IMAP primeiro; Graph se a empresa usar M365 com IMAP desativado | Fase 2 |
| 4 | **Biblioteca de componentes Vue** | (a) Reka UI (headless e acessível) + estilo próprio em Tailwind; (b) PrimeVue em modo *unstyled* com Tailwind; (c) componentes 100% próprios | (a): acessibilidade pronta (WCAG) sem brigar com o visual do Tailwind | Fase 0 |
| 5 | **Licença e distribuição** | Proprietário, código aberto (AGPL, MIT…) | Definir antes de distribuir para outras empresas | — |
| 6 | **Hospedagem do repositório e CI** | GitHub, GitLab, Azure DevOps | — | Fase 0 |
| 7 | **Política de retenção de dados** | Prazo para anonimizar chamados fechados e `ai_runs` | Definir com jurídico / DPO; deixar configurável por instalação | Fase 2 |

## Decididas

| Data | Decisão | ADR |
|------|---------|-----|
| 2026-10-09 | Python + PostgreSQL 16/17 | [0002](adr/0002-python-fastapi.md), [0003](adr/0003-postgresql.md) |
| 2026-10-09 | IA por uma única API genérica (compatível com OpenAI), sem código por provedor ou modelo; assistiva por padrão | [0004](adr/0004-ia-api-generica-e-assistiva.md) |
| 2026-10-09 | Uma instalação por empresa (single-tenant) | [0005](adr/0005-instalacao-por-empresa.md) |
| 2026-10-09 | Interface web: SPA em Vue 3 + TypeScript + Tailwind CSS (substitui o ADR 0006) | [0007](adr/0007-interface-web-vue.md) |
