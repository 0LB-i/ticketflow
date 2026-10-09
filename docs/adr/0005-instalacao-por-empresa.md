# 0005. Uma instalação por empresa (single-tenant)

- **Status:** Aceita
- **Data:** 2026-10-09

## Contexto

O sistema atende chamados internos de empresas. Precisávamos decidir se várias empresas compartilham uma mesma instalação (SaaS multi-tenant) ou se cada empresa tem a sua.

## Decisão

- Cada empresa tem **sua própria instalação**: processos da aplicação e banco PostgreSQL próprios.
- O schema **não** tem `tenant_id`. Toda a configuração (equipes, categorias, SLA, IA, marca) é da instalação.
- O produto é distribuído como **imagem Docker versionada**. Cada instalação aplica as migrações Alembic na atualização.
- A configuração de infraestrutura vem de variáveis de ambiente; a configuração funcional fica no banco e é editada pela tela de administração.

## Alternativas consideradas

- **`tenant_id` + Row-Level Security:** permite SaaS com custo menor por cliente, mas toda consulta, índice e teste precisa considerar o tenant, e um erro vaza dados entre empresas.
- **Um schema por empresa no mesmo banco:** isolamento intermediário, mas as migrações e a operação ficam mais complexas.

## Consequências

- Isolamento total de dados, o que simplifica LGPD, auditoria e a exigência de clientes que querem hospedar internamente.
- Schema e código mais simples.
- Cada instalação é atualizada e tem backup separado. É preciso um processo de atualização simples e documentado, e migrações sempre compatíveis com a versão anterior.
- Se no futuro surgir uma oferta SaaS, ela pode ser feita como "uma instalação por cliente" automatizada (ex.: Kubernetes), sem mudar o schema.
