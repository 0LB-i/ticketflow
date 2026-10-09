# 12. Processo de desenvolvimento (GitHub)

## 12.1 Organização do trabalho

| Elemento do GitHub | Uso |
|--------------------|-----|
| **Milestones** | Uma por fase: `Fase 0 — Fundação`, `Fase 1 — MVP`… |
| **GitHub Projects** | Quadro com colunas *Backlog → Pronto para desenvolver → Em andamento → Em revisão → Concluído*, campo **Iteração** (sprint de 2 semanas) e campo **Estimativa** |
| **Issues** | Uma por história ou tarefa, com o código do roadmap no título (ex.: `[F1-S3-07] Transferir chamado entre grupos`) |
| **Templates de issue** | *História de usuário*, *Bug*, *Tarefa técnica* |
| **Discussions** | Propostas e dúvidas abertas antes de virarem ADR |

### Labels

| Prefixo | Valores |
|---------|---------|
| `tipo:` | `feature`, `bug`, `tarefa`, `docs`, `seguranca` |
| `area:` | `backend`, `frontend`, `infra`, `ia`, `ux` |
| `modulo:` | `identidade`, `organizacao`, `chamados`, `anexos`, `notificacoes`, `kb`, `relatorios`, `integracoes` |
| `prioridade:` | `alta`, `media`, `baixa` |

### Modelo de história de usuário

```markdown
**Como** agente do Service Desk
**quero** transferir um chamado para outro grupo informando o motivo
**para** que a equipe certa atenda sem perder o histórico

### Critérios de aceite
- [ ] Só membros do grupo atual (ou admin) podem transferir
- [ ] Motivo obrigatório, registrado como nota interna
- [ ] Chamado continua "Pendente" no grupo de destino, sem responsável
- [ ] Grupo anterior mantém acesso somente leitura
- [ ] Evento `ticket.transferred` no histórico e no outbox

### Referências
docs/10-chamados.md#transferência-e-escalonamento
```

## 12.2 Branches, commits e pull requests

- **Desenvolvimento baseado no tronco** (*trunk-based*): `main` sempre implantável; branches curtas (`feat/F1-S3-07-transferencia`, `fix/...`), vivendo poucos dias.
- **Proteção da `main`:** só por PR, com CI verde, **1 aprovação** e branch atualizada. Merge por **squash**.
- **Título do PR** no padrão Conventional Commits (`feat(chamados): transferir entre grupos`). Ele vira a mensagem do commit e alimenta o CHANGELOG.
- **Template de PR:** o que muda, como testar, prints de tela (frontend), checklist da definição de pronto.
- **CODEOWNERS:** mudanças em `backend/src/chamados/core/permissions*`, migrações e `docs/adr/` exigem revisão de quem é responsável por essas áreas.

## 12.3 Definição de pronto

Uma issue só vai para *Concluído* quando:

- [ ] Critérios de aceite atendidos
- [ ] Testes automatizados: unitários e de integração (backend com banco real); componente ou ponta a ponta (frontend), quando aplicável
- [ ] **Testes de permissão** para qualquer endpoint novo ou alterado
- [ ] Migração Alembic reversível (`downgrade`) e compatível com a versão anterior da aplicação
- [ ] OpenAPI atualizada e cliente TypeScript regenerado
- [ ] Textos da interface no i18n (pt-BR), sem texto fixo no código
- [ ] Acessibilidade verificada: navegação por teclado, foco visível, rótulos
- [ ] Documentação em `docs/` atualizada quando a regra de negócio mudou
- [ ] Revisado e aprovado no PR

## 12.4 Integração contínua (GitHub Actions)

| Workflow | Quando roda | O que faz |
|----------|-------------|-----------|
| `backend.yml` | PR e push na `main` (mudanças em `backend/`) | `ruff check`, `ruff format --check`, `mypy`, `pytest` com cobertura. **Matriz PostgreSQL 16 e 17** usando as imagens `pgvector/pgvector:pg16` e `pg17` como *services* |
| `frontend.yml` | PR e push (mudanças em `frontend/`) | `pnpm install --frozen-lockfile`, ESLint, `vue-tsc`, Vitest, `vite build` |
| `contract.yml` | PR | Gera o OpenAPI do backend e o cliente TypeScript e falha se houver diferença não commitada |
| `e2e.yml` | PR para `main` e diariamente | Sobe a stack com Docker Compose e roda o Playwright |
| `codeql.yml` | Semanal e em PR | Análise de segurança (Python e JavaScript/TypeScript) |
| `release.yml` | Push na `main` | *release-please* abre ou atualiza o PR de release; quando ele é aprovado, cria a tag `vX.Y.Z` e o CHANGELOG |
| `docker.yml` | Tag `v*` | Build da imagem em várias etapas e publicação no **GitHub Container Registry** (`ghcr.io/<org>/sistema-chamados:X.Y.Z`), com SBOM e assinatura |

Também ficam ativos o **Dependabot** (pip/uv, npm/pnpm, GitHub Actions, Docker), o **secret scanning** e o **push protection**.

## 12.5 Versões e entregas

- **SemVer:** `MAJOR.MINOR.PATCH`. MAJOR exige um passo manual na atualização; MINOR traz funcionalidades; PATCH, correções.
- Cada release traz **notas de atualização** para quem administra uma instalação: migrações, novas variáveis de ambiente, mudanças de comportamento.
- As empresas atualizam trocando a tag da imagem; as migrações rodam na subida do container (ou com `chamados db upgrade`).
- Versões `0.x` até o M2; `1.0.0` ao fim da Fase 4.

## 12.6 Ambientes

| Ambiente | Para quê |
|----------|----------|
| **Local** | Desenvolvimento: Docker Compose (banco, Mailpit) + `uvicorn --reload` + `pnpm dev` |
| **CI** | Containers efêmeros por execução |
| **Homologação** | Instalação de teste, atualizada a cada merge na `main`; dados fictícios; usada nas validações com o piloto |
| **Produção** | Uma instalação por empresa, atualizada por tag de release |

## 12.7 Estratégia de testes

| Nível | Ferramenta | Cobre |
|-------|------------|-------|
| Unitário (backend) | pytest | Regras puras: matriz de prioridade, transições, mascaramento |
| Integração (backend) | pytest + testcontainers / services do CI | Repositórios, services e endpoints com PostgreSQL real |
| Permissões | pytest parametrizado | Matriz perfil × ação × situação do chamado ([08](08-organizacao-e-permissoes.md)) |
| Componentes (frontend) | Vitest + Vue Test Utils | Componentes e composables |
| Ponta a ponta | Playwright | Fluxos completos: abrir → atender → resolver → confirmar; aprovação; transferência |
| IA | Evals próprios | Qualidade de classificação, resumo e resposta por versão de prompt |

**Dados de teste:** *factories* (factory-boy) no backend e um comando `chamados dev seed`, que cria uma empresa fictícia com setores, grupos, usuários de todos os perfis e chamados em todos os status.
