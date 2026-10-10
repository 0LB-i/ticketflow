# 0009. GitHub como plataforma do projeto

- **Status:** Aceita
- **Data:** 2026-10-09

> **Nota (2026-10-10):** adiada. Por enquanto o repositório é **local** e a verificação roda por script ([12](../12-processo-de-desenvolvimento.md)). Esta decisão vale quando houver um remoto. As imagens no GHCR já tinham saído com o [ADR 0010](0010-producao-systemd.md).

## Contexto

Precisávamos definir onde ficam o código, o CI, o acompanhamento do trabalho e as imagens de release.

## Decisão

- **Código:** repositório no GitHub (monorepo `backend/` + `frontend/`).
- **CI/CD:** GitHub Actions.
- **Planejamento:** GitHub Issues + GitHub Projects (iterações = sprints, milestones = fases).
- **Imagens Docker:** GitHub Container Registry (`ghcr.io`).
- **Segurança:** Dependabot, CodeQL, secret scanning com push protection.
- **Releases:** tags SemVer e CHANGELOG gerados com release-please.

Detalhes do fluxo em [Processo de desenvolvimento](../12-processo-de-desenvolvimento.md).

## Consequências

- Tudo (código, tarefas, CI, imagens) fica num lugar só, com permissões unificadas.
- Cada empresa cliente baixa a imagem do `ghcr.io`. Se o repositório for privado, cada instalação precisa de um token de leitura de pacotes.
