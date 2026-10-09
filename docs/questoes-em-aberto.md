# Questões em aberto

Decisões pendentes, ordenadas pelo impacto. Quando uma for decidida, registre um ADR e mova a questão para "Decididas".

| # | Questão | Opções | Recomendação inicial | Bloqueia |
|---|---------|--------|----------------------|----------|
| 1 | **Uma instalação por empresa ou várias empresas na mesma instalação (SaaS multi-tenant)?** | (a) single-tenant; (b) `tenant_id` em todas as tabelas + Row-Level Security; (c) um schema por empresa | (a), se o produto for instalado em cada empresa. Se houver qualquer chance de SaaS, (b) desde o início, porque adicionar depois é caro | Modelo de dados (Fase 0) |
| 2 | **Tecnologia da interface web** | (a) Jinja2 + HTMX (só Python); (b) SPA em React/Vue consumindo a API; (c) só API agora e frontend depois | (a) para o MVP: equipe só Python, menos complexidade, e a API continua completa para outros clientes | Fase 1 |
| 3 | **Provedores de IA prioritários** | Claude (Anthropic), OpenAI / Azure OpenAI, Google, modelo local (Ollama / vLLM) | 1 provedor em nuvem + 1 local, para cobrir dados sensíveis. Depende de contratos e política de dados da empresa | Fase 3 |
| 4 | **Modelo de embeddings e dimensão do vetor** | Depende do provedor; a dimensão fica fixa na coluna `vector(n)` | Escolher com testes em chamados reais em português | Fase 3 |
| 5 | **Armazenamento de anexos** | Disco local / volume, S3-compatível (MinIO, AWS, Azure Blob) | Interface de armazenamento com os dois adaptadores; S3 em produção | Fase 1 |
| 6 | **Provedor de identidade** | Entra ID, Google Workspace, Keycloak, LDAP | OIDC genérico cobre os três primeiros | Fase 2 |
| 7 | **Entrada por e-mail** | IMAP genérico, Microsoft Graph, Gmail API | IMAP primeiro; Graph se o cliente usar M365 com IMAP desativado | Fase 2 |
| 8 | **Licença e distribuição** | Proprietário interno, código aberto (AGPL, MIT…) | Definir antes de aceitar contribuições externas | — |
| 9 | **Hospedagem do repositório e CI** | GitHub, GitLab, Azure DevOps | — | Fase 0 |
| 10 | **Política de retenção de dados** | Prazo para anonimizar chamados fechados e `ai_runs` | Definir com jurídico / DPO | Fase 2 |

## Decididas

| # | Decisão | ADR |
|---|---------|-----|
| — | Python + PostgreSQL 16/17 | [0002](adr/0002-python-fastapi.md), [0003](adr/0003-postgresql.md) |
| — | IA via camada de provedores intercambiáveis, assistiva por padrão | [0004](adr/0004-ia-agnostica-e-assistiva.md) |
