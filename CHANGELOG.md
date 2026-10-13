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
- Sprint 3 (API): categorias em árvore (grupo e tipo padrão, confidencial); status padrão (Pendente, Aguardando, Concluído, Cancelado) e códigos de resolução; registro de chamados com roteamento pela categoria e prioridade pela matriz impacto × urgência; comentários (edição por 10 minutos), @menções e observadores; assumir, atribuir, devolver e transferir; aguardar, retomar, concluir, reabrir e cancelar; histórico do chamado; filtro único de visibilidade, com auditoria do acesso de admin e auditor a chamados confidenciais.
- Sprint 3 (telas): novo chamado, detalhe do chamado (linha do tempo, comentários com editor Tiptap e @menções, ações de status, atribuição, transferência, observadores, edição de campos e prioridade), lista simples de chamados e administração de categorias. Botão "Novo chamado" no cabeçalho.
- Configurações (`/admin/configuracoes`): idioma padrão do sistema (português ou inglês) e idioma de cada usuário no menu do usuário; as três cores da identidade, com a paleta derivada e os tons ajustados para manter o contraste; logotipo da empresa. Interface, mensagens de erro da API e e-mails em inglês.
- Migração `0005`: tabela `settings` e `users.locale`.
- Cliente e contato no chamado: o registro e a edição escolhem um cliente do cadastro (busca por nome ou CPF/CNPJ) e informam quem pediu; a lista de chamados mostra o cliente. Migração `0011`: `tickets.client_id`.
- Filas na lista de chamados (Não atribuídos, Meus, Com novidades, Aguardando, Acompanhando, Todos) com contadores e filtros na URL; aviso de comentário novo de outra pessoa desde a última visita; botão "Pegar o próximo"; busca em português, sem acentos, no título, na descrição, nos comentários, no cliente e no contato, a partir do cabeçalho. Migração `0012`: `ticket_reads` e as colunas de busca.
- Anexos: botão "Anexar" com arrastar e soltar no registro e nos comentários (inclusive na conclusão), imagens coladas no editor, lista de anexos no chamado; download só para quem vê o chamado. Tipos conferidos pelo conteúdo; 25 MB por arquivo, 10 por envio e 200 MB por chamado. Migração `0013`: `attachments`. Os arquivos ficam em `FILES_DIR` (padrão `/var/lib/ticketflow/files`). Até o worker existir, agende `chamados attachments purge` (diário) para apagar os envios esquecidos.
- Migração `0004`: categorias, status, códigos de resolução, chamados, grupos que atuaram, observadores, comentários e histórico (só aceita inserção).

### Mudado

- Identificadores da instalação passam a ser `ticketflow`: código em `/opt/ticketflow`, serviços `ticketflow`, `ticketflow-worker` e `ticketflow-backup` (units em `deploy/ticketflow*.service`), usuário do sistema e papel no PostgreSQL `ticketflow`, configuração em `/etc/ticketflow/env`, anexos em `/var/lib/ticketflow/files` e backups em `/var/backups/ticketflow`. O banco (`chamados`) e o comando `chamados` não mudam.

### Variáveis de ambiente

- `DATABASE_URL`, `LOG_LEVEL`, `LOG_FORMAT` (`json` em produção).
- `FILES_DIR`: pasta dos anexos (padrão `/var/lib/ticketflow/files`).
- `APP_BASE_URL` (endereço usado nos links dos e-mails), `COOKIE_SECURE`, `SESSION_IDLE_HOURS`, `SESSION_MAX_DAYS`.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_STARTTLS`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`. Sem `SMTP_HOST`, os e-mails vão para o log.
