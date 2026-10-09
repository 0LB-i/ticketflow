# 7. Roadmap

As fases são sequenciais; as entregas dentro de cada fase podem andar em paralelo. As durações são estimativas para uma equipe de 2 a 3 desenvolvedores e serão revistas ao fim de cada fase.

## Fase 0 — Fundação (≈ 2 semanas)

- [x] Decidir as questões bloqueantes: instalação por empresa, interface web, IA genérica
- [ ] Esqueleto do projeto: `pyproject.toml` (uv), estrutura `src/chamados`, FastAPI com `/health`
- [ ] Docker Compose: PostgreSQL 17 + pgvector, Mailpit
- [ ] Layout base da interface: Jinja2 + HTMX + Tailwind (CLI standalone integrado ao build da imagem)
- [ ] SQLAlchemy + Alembic; primeira migração a partir do [esboço do schema](esboco-schema.sql)
- [ ] CI (GitHub Actions ou GitLab CI): ruff, mypy, pytest com testcontainers em **PG 16 e 17**
- [ ] Configuração via variáveis de ambiente (pydantic-settings), logs estruturados
- [ ] Autenticação local (Argon2id), sessão e RBAC básico

**Pronto quando:** `docker compose up` sobe a API, a migração roda e o CI fica verde nas duas versões do PostgreSQL.

## Fase 1 — MVP de chamados (≈ 6 semanas)

- [ ] Usuários, equipes, categorias e status (CRUD administrativo)
- [ ] Abrir, listar, filtrar e ver chamados
- [ ] Transições de status com validação de fluxo
- [ ] Atribuição a equipe e agente; roteamento por categoria
- [ ] Comentários públicos e internos; anexos
- [ ] Histórico (`ticket_events`) e linha do tempo
- [ ] Outbox + worker + fila de tarefas no PostgreSQL
- [ ] Notificações por e-mail
- [ ] Busca textual em português
- [ ] Interface web para solicitante e agente
- [ ] API documentada (OpenAPI)

**Pronto quando:** uma equipe piloto (ex.: TI) consegue operar o dia a dia só pelo sistema.

## Fase 2 — Operação e integrações (≈ 5 semanas)

- [ ] SLA: políticas, calendário de expediente, pausa, alertas
- [ ] SSO via OIDC (Entra ID / Google / Keycloak)
- [ ] Tokens de API com escopos; `Idempotency-Key`; rate limit
- [ ] Webhooks de saída assinados
- [ ] Abertura e resposta por e-mail (IMAP / Microsoft Graph)
- [ ] Campos personalizados por categoria
- [ ] Observadores, vínculos entre chamados, tags, visões salvas
- [ ] Pesquisa de satisfação
- [ ] Painel e relatórios; exportação CSV
- [ ] Base de conhecimento (sem IA)

**Pronto quando:** todas as equipes piloto migraram e os indicadores de SLA estão confiáveis.

## Fase 3 — IA assistiva (≈ 5 semanas)

- [ ] Módulo `ai`: cliente genérico (chat + embeddings), saída JSON validada com Pydantic
- [ ] Testes do cliente contra um servidor falso e contra um modelo local real (ex.: Ollama no CI)
- [ ] Administração de endpoints de IA e funcionalidades; registro de execuções (`ai_runs`)
- [ ] Mascaramento de dados pessoais + bloqueio por categoria
- [ ] Embeddings com pgvector; busca semântica e híbrida
- [ ] Classificação automática (modo sugestão)
- [ ] Resumo do chamado
- [ ] Sugestão de resposta com RAG e fontes citadas
- [ ] Chamados semelhantes / duplicados
- [ ] Feedback (aceitar / editar / rejeitar) e painel de qualidade e custo
- [ ] Conjunto de avaliação (evals) para cada prompt, rodando no CI

**Pronto quando:** taxa de aceitação de classificação ≥ 70% em modo sugestão por 4 semanas, e o sistema continua funcionando com a IA desligada.

## Fase 4 — IA agêntica e autoatendimento (≈ 4 semanas)

- [ ] Servidor MCP (ferramentas sobre os services)
- [ ] Contas de serviço para agentes de IA; políticas de escopo
- [ ] Deflexão no portal (sugerir artigos antes de abrir o chamado)
- [ ] Rascunho de artigo a partir de chamado resolvido
- [ ] Classificação com aplicação automática (onde a qualidade medida justificar)
- [ ] Integração com Teams / Slack (bot que abre e consulta chamados)

## Depois

- Automações configuráveis (regras se X então Y)
- Atribuição automática por carga
- Particionamento de `ticket_events` e `ai_runs`
- Catálogo de serviços com aprovações
