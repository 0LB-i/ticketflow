# Changelog

Notas de cada versão para quem administra uma instalação: migrações, novas variáveis de ambiente e mudanças de comportamento ([docs/12 §12.5](docs/12-processo-de-desenvolvimento.md#125-versões-e-entregas)). Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões em [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado

- Fase 0: esqueleto do backend (FastAPI, `/api/health`, erros RFC 9457, comando `chamados`) e do frontend (Vue 3, design system inicial, layout, modo claro e escuro).
- Migração `0001`: extensões `citext`, `unaccent`, `pg_trgm` e a configuração de busca `pt_br`.
- Scripts de verificação, deploy e backup; arquivos do systemd e do nginx.

### Variáveis de ambiente

- `DATABASE_URL`, `LOG_LEVEL`, `LOG_FORMAT` (`json` em produção).
