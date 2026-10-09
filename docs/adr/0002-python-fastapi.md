# 0002. Python 3.12+ com FastAPI e SQLAlchemy

- **Status:** Proposta
- **Data:** 2026-10-09

## Contexto

Python é requisito. O sistema é API-first, precisa de documentação OpenAPI para integrações e agentes de IA, e fará muitas chamadas de rede (provedores de IA, webhooks, e-mail).

## Decisão

- **FastAPI** como framework web, **Pydantic v2** para schemas (requisições, respostas e saídas estruturadas de IA).
- **SQLAlchemy 2.x** (modo async) com **psycopg 3**; **Alembic** para migrações.
- **uv** para dependências; **ruff** + **mypy** + **pytest** para qualidade.
- Arquitetura de **monólito modular** (ver [arquitetura](../03-arquitetura.md)).

## Alternativas consideradas

- **Django + DRF:** admin pronto e ORM maduro, mas é síncrono por natureza (o suporte async é parcial), a OpenAPI fica menos natural e a stack é mais pesada para um sistema API-first. Seria uma boa escolha se o admin do Django fosse um diferencial forte.
- **Litestar:** tecnicamente excelente, mas tem comunidade menor.
- **SQLModel:** reduz a duplicação entre modelos e schemas, mas fica atrás do SQLAlchemy em recursos avançados.

## Consequências

- Sem um admin pronto: as telas administrativas precisam ser construídas.
- Código async exige cuidado com bibliotecas bloqueantes (usar versões async ou thread pool).
