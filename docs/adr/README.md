# Architecture Decision Records (ADRs)

Cada decisão de arquitetura relevante é registrada em um arquivo numerado, usando o [modelo](template.md).

| ADR | Título | Status |
|-----|--------|--------|
| [0001](0001-registro-de-decisoes.md) | Registrar decisões em ADRs e convenções de idioma | Aceita |
| [0002](0002-python-fastapi.md) | Python 3.12+ com FastAPI e SQLAlchemy | Proposta |
| [0003](0003-postgresql.md) | PostgreSQL 17 com suporte a 16, e o banco como fila e motor de busca | Proposta |
| [0004](0004-ia-api-generica-e-assistiva.md) | IA por uma API genérica, sem código por provedor ou modelo, e assistiva por padrão | Aceita |
| [0005](0005-instalacao-por-empresa.md) | Uma instalação por empresa (single-tenant) | Aceita |
| [0006](0006-interface-web.md) | Interface web com Jinja2 + HTMX + Tailwind CSS | Substituída por 0007 |
| [0007](0007-interface-web-vue.md) | Interface web: SPA em Vue 3 + TypeScript + Tailwind CSS | Substituída por 0011 |
| [0008](0008-reka-ui.md) | Componentes de interface com Reka UI + Tailwind CSS | Substituída por 0011 |
| [0009](0009-github.md) | GitHub como plataforma do projeto | Aceita (adiada: repositório local por enquanto) |
| [0010](0010-producao-systemd.md) | Produção com systemd + uvicorn, sem Docker | Aceita |
| [0011](0011-interface-web-no-servidor.md) | Interface web renderizada no servidor: Jinja2 + HTMX + Tailwind CSS | Aceita (migração concluída em 2026-10-19) |
