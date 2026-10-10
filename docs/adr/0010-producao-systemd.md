# 0010. Produção com systemd + uvicorn, sem Docker

- **Status:** Aceita
- **Data:** 2026-10-09
- **Altera:** a forma de entrega descrita nos ADRs [0005](0005-instalacao-por-empresa.md) (imagem Docker), [0007](0007-interface-web-vue.md) (frontend servido pelo container) e [0009](0009-github.md) (imagens no GHCR)

## Contexto

A primeira instalação é a da empresa: até 50 usuários, um único servidor Linux. O CLAUDE.md já trata a aplicação como um serviço systemd (`sistema-chamados.service`) rodando uvicorn.

## Decisão

- **Sem Docker em produção.** O Docker Compose continua só no desenvolvimento (PostgreSQL + Mailpit).
- **Serviços systemd:**
  - `sistema-chamados.service`: uvicorn servindo a API e os arquivos estáticos da SPA (`frontend/dist`), escutando só em `127.0.0.1`;
  - `sistema-chamados-worker.service`: fila de tarefas e rotinas periódicas.
- **nginx** na frente: HTTPS, limite de tamanho de upload e cabeçalhos de segurança, repassando para o uvicorn.
- **PostgreSQL 17** do repositório oficial do PostgreSQL (`apt.postgresql.org`) no mesmo servidor (o pacote do pgvector só quando a IA entrar).
- **Logs** em stdout, capturados pelo journald (`journalctl -u sistema-chamados`). Nenhum arquivo de log próprio da aplicação.
- **Atualização** com um script de deploy no repositório (`scripts/deploy.sh`): `git pull` na `main`, `uv sync --frozen`, build do frontend (`pnpm build`) e `chamados db upgrade`. **Quem reinicia os serviços é o usuário** (regra do CLAUDE.md); o script só prepara tudo e avisa.
- **Arquivos de anexos** em diretório local (`/var/lib/sistema-chamados/files`).
- **Backup:** `pg_dump` diário + cópia do diretório de anexos, com retenção e teste de restauração documentados.

## Alternativas consideradas

- **Docker Compose:** isola dependências, mas acrescenta uma camada que a equipe não usa no dia a dia.
- **Pacote gerado pelo CI** (backend + frontend compilado): dispensa Node.js no servidor. Pode substituir o build no servidor no futuro, sem mudar o resto.

## Consequências

- O servidor precisa de Python (via uv), Node.js + pnpm (só para compilar o frontend), PostgreSQL 17 e nginx.
- Os arquivos de exemplo (`deploy/sistema-chamados.service`, `deploy/sistema-chamados-worker.service`, `deploy/nginx.conf`) passam a fazer parte da Fase 0.
- Não há imagens publicadas no GHCR.
