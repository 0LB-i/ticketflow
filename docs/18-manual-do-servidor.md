# 18. Manual do servidor

Instalação, atualização, backup e diagnóstico do TicketFlow em produção, seguindo o [ADR 0010](adr/0010-producao-systemd.md): serviços systemd + nginx + PostgreSQL 17 num único servidor **Ubuntu 24.04 LTS**.

> Os arquivos citados em `deploy/` e `scripts/` são criados na Fase 0 (`F0-09`). Os comandos abaixo são a referência para escrevê-los e devem ser conferidos na primeira instalação real.

## 18.1 Visão geral

```
navegador ──HTTPS──► nginx :443 ──► uvicorn 127.0.0.1:8000 (ticketflow.service)
                                           │                    │
                                           ▼                    ▼
                                    PostgreSQL 17 ◄──── worker (ticketflow-worker.service)
                                    (socket local)
```

| Item | Onde |
|------|------|
| Código (checkout da `main`) | `/opt/ticketflow` |
| Repositório Git de passagem (recebe o `git push`) | `/srv/git/ticketflow.git` |
| Configuração e segredos | `/etc/ticketflow/env` |
| Anexos | `/var/lib/ticketflow/files` |
| Backups locais | `/var/backups/ticketflow` |
| Usuário do sistema que roda os serviços | `ticketflow` |
| Banco de dados / papel no PostgreSQL | `chamados` / `ticketflow` (autenticação *peer*, sem senha) |
| Logs | journald: `journalctl -u ticketflow -u ticketflow-worker` |

## 18.2 Requisitos

- **Servidor:** Ubuntu 24.04 LTS, 2 vCPU, 4 GB de RAM, 50 GB de disco ([questão 2](questoes-em-aberto.md)).
- **Endereço:** um nome no DNS da empresa (ex.: `ticketflow.example.com`) apontando para o servidor.
- **Certificado HTTPS**, uma das opções:
  - **Let's Encrypt** com `certbot`, se o servidor for acessível pela internet na porta 80;
  - Let's Encrypt com **desafio por DNS**, se o servidor for só da rede interna e o DNS do domínio permitir;
  - **certificado da empresa**, se a empresa já tiver um.
- **E-mail de envio (SMTP):** a definir ([questão 1](questoes-em-aberto.md)). Sem ele, convites e notificações não saem.
- **Destino da cópia externa do backup** (outro servidor, NAS ou armazenamento em nuvem): a definir ([questão 13](questoes-em-aberto.md)).

## 18.3 Instalação

Todos os comandos rodam como um usuário administrador com `sudo`.

### 1. Sistema operacional

```bash
sudo apt update && sudo apt full-upgrade -y
sudo timedatectl set-timezone America/Sao_Paulo
sudo apt install -y git curl ca-certificates nginx unattended-upgrades ufw
sudo dpkg-reconfigure -plow unattended-upgrades       # atualizações de segurança automáticas
sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw enable
```

O acesso SSH deve ser só por chave (`PasswordAuthentication no` em `/etc/ssh/sshd_config`).

### 2. Usuário e diretórios

```bash
sudo adduser --system --group --home /var/lib/ticketflow ticketflow
sudo install -d -o ticketflow -g ticketflow -m 750 /var/lib/ticketflow/files
sudo install -d -o ticketflow -g ticketflow -m 755 /opt/ticketflow
sudo install -d -o root -g ticketflow -m 750 /etc/ticketflow
sudo install -d -o ticketflow -g ticketflow -m 700 /var/backups/ticketflow
```

### 3. PostgreSQL 17

```bash
sudo apt install -y postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh      # adiciona o repositório oficial
sudo apt install -y postgresql-17
sudo -u postgres createuser ticketflow
sudo -u postgres createdb -O ticketflow chamados
```

- O banco escuta só no socket local e em `localhost` (padrão do pacote). Não abrir a porta 5432 no firewall.
- As extensões da v1.0 (`unaccent`, `pg_trgm`, `citext`) são *trusted*: a própria migração as cria, sem superusuário.

### 4. Python (uv) e Node.js

```bash
curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo bash -
sudo apt install -y nodejs
sudo corepack enable                                  # disponibiliza o pnpm na versão do package.json
```

O Python 3.12 do Ubuntu 24.04 atende ao projeto. O Node.js só é usado para compilar o frontend.

### 5. Código

O repositório de desenvolvimento é local ([12.1](12-processo-de-desenvolvimento.md#121-repositório-e-tarefas)). O servidor recebe o código por um repositório Git de passagem:

```bash
# no servidor
sudo install -d -o $USER -g $USER /srv/git
git init --bare -b main /srv/git/ticketflow.git

# na máquina de desenvolvimento
git remote add producao ssh://USUARIO@SERVIDOR/srv/git/ticketflow.git
git push producao main

# no servidor
sudo -u ticketflow git clone /srv/git/ticketflow.git /opt/ticketflow
```

Esse repositório de passagem também é uma **cópia do código fora da máquina de desenvolvimento**. Quando houver um remoto no GitHub, o checkout passa a buscar dele.

### 6. Configuração

`/etc/ticketflow/env` (dono `root`, grupo `ticketflow`, permissão `640`):

```bash
APP_BASE_URL=https://ticketflow.example.com
DATABASE_URL=postgresql+psycopg://ticketflow@/chamados?host=/var/run/postgresql
SECRET_KEY=                       # gerar com: openssl rand -hex 32  (nunca reutilizar nem versionar)
FILES_DIR=/var/lib/ticketflow/files
SMTP_HOST=                        # a definir (questão 1)
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM="TicketFlow – empresa <ticketflow@example.com>"
```

Trocar o `SECRET_KEY` encerra todas as sessões e invalida os convites pendentes.

### 7. Primeira compilação e banco

```bash
sudo -u ticketflow /opt/ticketflow/scripts/deploy.sh
```

O script faz `git pull`, `uv sync --frozen`, `pnpm install --frozen-lockfile && pnpm build` e `chamados db upgrade`, e no fim lembra de reiniciar os serviços.

### 8. Serviços systemd

```bash
sudo cp /opt/ticketflow/deploy/ticketflow*.service /etc/systemd/system/
sudo cp /opt/ticketflow/deploy/ticketflow-backup.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ticketflow ticketflow-backup.timer
sudo systemctl enable --now ticketflow-worker     # só a partir da Sprint 4, quando o worker existir
```

Pontos principais de `deploy/ticketflow.service`:

```ini
[Service]
User=ticketflow
EnvironmentFile=/etc/ticketflow/env
WorkingDirectory=/opt/ticketflow/backend
ExecStart=/opt/ticketflow/backend/.venv/bin/uvicorn chamados.main:create_app --factory \
          --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/var/lib/ticketflow
```

O `ticketflow-worker.service` é igual, com `ExecStart=.../.venv/bin/chamados worker`. Os arquivos completos estão em [`deploy/`](../deploy/).

### 9. nginx e HTTPS

```bash
sudo cp /opt/ticketflow/deploy/nginx.conf /etc/nginx/sites-available/ticketflow
sudo ln -s /etc/nginx/sites-available/ticketflow /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo apt install -y certbot python3-certbot-nginx && sudo certbot --nginx -d ticketflow.example.com
```

Pontos principais de `deploy/nginx.conf`:

- redireciona HTTP para HTTPS; `client_max_body_size 30m` (anexos de até 25 MB, [11.3](11-anexos-e-arquivos.md#113-limites-padrões-configuráveis));
- `proxy_pass http://127.0.0.1:8000` com `X-Forwarded-For` e `X-Forwarded-Proto`;
- cabeçalhos: `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` e uma `Content-Security-Policy` restrita à própria origem.

### 10. Primeiro acesso e verificação

```bash
curl -fsS https://ticketflow.example.com/api/health
```

**Logo em seguida**, entre no sistema com o usuário `admin` e a senha `admin` e troque a senha na tela que aparece ([9.2](09-login-e-autenticacao.md#92-primeiro-acesso-à-instalação)). Até essa troca, qualquer pessoa que alcance o servidor pode entrar como administrador. Depois, cadastre um e-mail para o usuário `admin` na tela de usuários. A carga inicial segue o [documento 15](15-estrutura-inicial.md).

Se todos os administradores perderem a senha, crie outro pela linha de comando:

```bash
sudo -u ticketflow bash -c 'cd /opt/ticketflow/backend && set -a && . /etc/ticketflow/env && .venv/bin/chamados admin create --email ti@example.com --name "Administrador"'
```

## 18.4 Atualização

```bash
# na máquina de desenvolvimento, com a verificação local passando (12.3)
git push producao main

# no servidor
sudo -u ticketflow /opt/ticketflow/scripts/deploy.sh
sudo systemctl restart ticketflow ticketflow-worker
curl -fsS https://ticketflow.example.com/api/health
```

- O `deploy.sh` faz um **backup do banco antes de rodar as migrações**.
- Reiniciar os serviços é sempre um passo manual e consciente ([ADR 0010](adr/0010-producao-systemd.md)). Avisar a equipe antes: a interrupção dura poucos segundos.
- Cada versão traz notas de atualização ([12.5](12-processo-de-desenvolvimento.md#125-versões-e-entregas)). Ler antes de atualizar.

**Voltar à versão anterior:** `git checkout <tag anterior>` no servidor, `chamados db downgrade <revisão>` se a versão nova tinha migração, `deploy.sh` e reinício. Se a migração não puder ser desfeita, restaurar o backup feito pelo `deploy.sh` (18.5).

## 18.5 Backup e restauração

**Backup diário** (`ticketflow-backup.timer`, às 02:00, roda `scripts/backup.sh`):

1. `pg_dump -Fc chamados` → `/var/backups/ticketflow/db-AAAA-MM-DD.dump`;
2. `rsync -a --delete` dos anexos → `/var/backups/ticketflow/files/`;
3. apaga dumps com mais de 14 dias;
4. **copia para fora do servidor** (destino da questão 13). Um backup que fica só no próprio servidor não protege contra perda do disco.

**Restauração** (testar antes da virada, no D−15 de [16.3](16-implantacao.md#163-cronograma), e depois a cada 3 meses):

```bash
sudo systemctl stop ticketflow ticketflow-worker
sudo -u ticketflow pg_restore --clean --if-exists -d chamados /var/backups/ticketflow/db-AAAA-MM-DD.dump
sudo -u ticketflow rsync -a --delete /var/backups/ticketflow/files/ /var/lib/ticketflow/files/
sudo systemctl start ticketflow ticketflow-worker
```

Banco e anexos precisam ser da **mesma data**; anexos mais novos que o banco ficam órfãos e são ignorados.

## 18.6 Rotina e monitoramento

| O quê | Como | Frequência |
|-------|------|------------|
| Serviços no ar | `systemctl status ticketflow ticketflow-worker` ou `/api/health` (confere o banco) | Diária, ou por um monitor externo |
| Erros | `journalctl -u ticketflow -p warning --since today` | Semanal |
| Backup rodou | `systemctl list-timers ticketflow-backup.timer` e data do último arquivo | Semanal |
| Espaço em disco | `df -h /var/lib /var/backups` | Mensal |
| Certificado | O `certbot` renova sozinho; conferir com `sudo certbot certificates` | Mensal |
| Atualizações do sistema | Automáticas (segurança); reiniciar o servidor quando `/var/run/reboot-required` existir | Mensal |

## 18.7 Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---------|----------------|-------------|
| Página "502 Bad Gateway" | Serviço da API parado | `systemctl status ticketflow`; ver o erro em `journalctl -u ticketflow -n 100` |
| E-mails não chegam | Worker parado ou SMTP errado | `systemctl status ticketflow-worker`; procurar `smtp` no journal; conferir `/etc/ticketflow/env` |
| Upload falha com erro 413 | Limite do nginx menor que o do sistema | Ajustar `client_max_body_size` e recarregar o nginx |
| Todos foram desconectados | `SECRET_KEY` mudou ou o banco foi restaurado | Esperado; cada um entra de novo |
| Serviço não sobe depois de atualizar | Migração falhou ou dependência faltando | Ler o fim da saída do `deploy.sh`; voltar à versão anterior (18.4) |
| Disco cheio | Anexos ou backups locais | Conferir `/var/backups`; aumentar o disco |
| Navegador avisa que o site não é seguro | Certificado vencido | `sudo certbot renew` e recarregar o nginx |
