# Changelog

Notas de cada versão para quem administra uma instalação: migrações, novas variáveis de ambiente e mudanças de comportamento ([docs/12 §12.5](docs/12-processo-de-desenvolvimento.md#125-versões-e-entregas)). Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões em [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado

- Fase 0: esqueleto do backend (FastAPI, `/api/health`, erros RFC 9457, comando `chamados`) e do frontend (Vue 3, design system inicial, layout, modo claro e escuro).
- Migração `0001`: extensões `citext`, `unaccent`, `pg_trgm` e a configuração de busca `pt_br`.
- Scripts de verificação, deploy e backup; arquivos do systemd e do nginx.

- Sprint 2: login por e-mail e senha com sessões no servidor e CSRF, proteção contra força bruta, convite e redefinição de senha, troca de senha; administração de usuários, grupos e setores atendidos; catálogo de permissões e papéis; log de auditoria.
- Migração `0002`: papéis, usuários, sessões, tokens de acesso, grupos, setores atendidos e auditoria.
- Administrador padrão `admin` / `admin`, com troca obrigatória da senha no primeiro acesso; login por e-mail ou nome de usuário; senha com no mínimo 8 caracteres (migração `0003`).
- Comando `chamados admin create` para criar outro administrador (recuperação de acesso).

### Variáveis de ambiente

- `DATABASE_URL`, `LOG_LEVEL`, `LOG_FORMAT` (`json` em produção).
- `APP_BASE_URL` (endereço usado nos links dos e-mails), `COOKIE_SECURE`, `SESSION_IDLE_HOURS`, `SESSION_MAX_DAYS`.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_STARTTLS`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`. Sem `SMTP_HOST`, os e-mails vão para o log.
