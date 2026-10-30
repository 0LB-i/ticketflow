# 18. Manual do servidor

Instalação, atualização e diagnóstico do TicketFlow em produção, seguindo o [ADR 0010](adr/0010-producao-systemd.md): serviços systemd + nginx + PostgreSQL 17 num único servidor **Ubuntu 24.04 LTS**.

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
| Código (checkout da `main`, buscado do GitHub) | `/opt/ticketflow` |
| Configuração e segredos | `/etc/ticketflow/env` |
| Anexos | `/var/lib/ticketflow/files` |
| Usuário do sistema que roda os serviços | `ticketflow` |
| Banco de dados / papel no PostgreSQL | `chamados` / `ticketflow` (autenticação *peer*, sem senha) |
| Logs | journald: `journalctl -u ticketflow -u ticketflow-worker` |

## 18.2 Requisitos

- **Servidor:** Ubuntu 24.04 LTS, 8 vCPU, 4 GB de RAM, 50 GB de disco ([questão 2](questoes-em-aberto.md)). Os núcleos definem quantos workers o uvicorn usa (18.3, passo 8).
- **Endereço:** um nome no DNS da empresa (ex.: `ticketflow.example.com`) apontando para o servidor.
- **Certificado HTTPS**, uma das opções:
  - **Let's Encrypt** com `certbot`, se o servidor for acessível pela internet na porta 80;
  - Let's Encrypt com **desafio por DNS**, se o servidor for só da rede interna e o DNS do domínio permitir;
  - **certificado da empresa**, se a empresa já tiver um.
- **E-mail de envio (SMTP):** a definir ([questão 1](questoes-em-aberto.md)). Sem ele, convites e notificações não saem.

## 18.3 Instalação

Todos os comandos rodam como um usuário administrador com `sudo`.

**Instalação automática:** o `install.sh` da raiz do repositório faz os passos 2 a 9 abaixo (com o código vindo do GitHub, só com o que a produção usa: sem testes, benchmark, `docs/` nem os scripts de desenvolvimento). Depois dele, falta só o passo 10:

```bash
curl -fsSLO https://raw.githubusercontent.com/0LB-i/ticketflow/main/install.sh
sudo bash install.sh            # domínio padrão ticketflow.local; ou: sudo bash install.sh DOMINIO
```

No lugar do passo 9, ele configura o nginx em HTTPS com um **certificado autoassinado** (`/etc/ticketflow/tls/ticketflow.crt`), sem o `Strict-Transport-Security`, que impediria seguir com ele. O domínio de verdade se ajusta depois: `server_name` e certificado em `/etc/nginx/sites-available/ticketflow` (ou `certbot --nginx -d DOMINIO`), `APP_BASE_URL` no `/etc/ticketflow/env`, e então `systemctl reload nginx` e `systemctl restart ticketflow`.

Pode rodar de novo: mantém o `/etc/ticketflow/env`, o banco e o certificado, e não reinicia os serviços que já estão no ar. Do passo 1, ele só acerta o fuso (`America/Sao_Paulo`, ou o da variável `FUSO`), e só numa máquina ainda em UTC; as atualizações automáticas, o firewall e o SSH continuam com quem administra o servidor.

### 1. Sistema operacional

```bash
sudo apt update && sudo apt full-upgrade -y
sudo timedatectl set-timezone America/Sao_Paulo   # o TicketFlow usa o fuso da máquina
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

### 4. Python (uv)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh
```

O Python 3.12 do Ubuntu 24.04 atende ao projeto. O servidor não precisa de Node.js: as telas são renderizadas pelo próprio backend e o CSS é gerado pelo binário standalone do Tailwind ([ADR 0011](adr/0011-interface-web-no-servidor.md)). Numa instalação de antes de 2026-10-19, o Node.js e o pnpm podem ser removidos, e a pasta `frontend/` que sobrou (o `dist` e o `node_modules`) pode ser apagada.

### 5. Código

O servidor busca o código do [GitHub](https://github.com/0LB-i/ticketflow):

```bash
sudo install -d -o ticketflow -g ticketflow /opt/ticketflow
sudo -u ticketflow git clone https://github.com/0LB-i/ticketflow.git /opt/ticketflow
```

O `install.sh` faz um checkout esparso, sem o que só o desenvolvimento usa (a lista está no `FORA_DA_PRODUCAO` do script); o `update.sh` respeita o mesmo filtro.

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
SMTP_FROM="TicketFlow – Empresa <ticketflow@example.com>"
```

Trocar o `SECRET_KEY` encerra todas as sessões e invalida os convites pendentes.

### 7. Primeira compilação e banco

```bash
sudo /opt/ticketflow/update.sh
```

O script (18.4) busca a `main`, faz `uv sync --frozen`, gera o CSS das telas do servidor (`scripts/css.sh`, que na primeira vez baixa o binário do Tailwind do GitHub) e `chamados db upgrade`, e no fim lembra de reiniciar os serviços.

### 8. Serviços systemd

```bash
sudo cp /opt/ticketflow/deploy/ticketflow*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ticketflow ticketflow-worker
```

Pontos principais de `deploy/ticketflow.service`:

```ini
[Service]
User=ticketflow
EnvironmentFile=/etc/ticketflow/env
WorkingDirectory=/opt/ticketflow/backend
ExecStart=/opt/ticketflow/backend/.venv/bin/uvicorn chamados.main:create_app --factory \
          --host 127.0.0.1 --port 8000 --workers 4 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/var/lib/ticketflow
```

**Workers:** `--workers 4` sobe 4 processos da API, que atendem ao mesmo tempo: uma pessoa gerando um relatório pesado não faz as outras esperarem. O número vale para 8 núcleos; com outro servidor, use cerca da metade dos núcleos, porque o PostgreSQL, o worker de e-mails e o nginx usam os mesmos. Cada worker abre até 15 conexões com o banco: 4 workers ficam bem abaixo do limite padrão de 100 do PostgreSQL. Mudar o número pede `sudo systemctl daemon-reload && sudo systemctl restart ticketflow`.

O `ticketflow-worker.service` é igual, com `ExecStart=.../.venv/bin/chamados worker`: ele consome a fila de tarefas (e-mails dos chamados) e roda as rotinas diárias, como a limpeza dos anexos não vinculados, às 03:00. Não precisa de cron. Ele **acompanha o `ticketflow`** (`PartOf` e `WantedBy=ticketflow.service`): sobe, para e reinicia junto com ele, mas continua um processo à parte, com o próprio log (`journalctl -u ticketflow-worker`). Os arquivos completos estão em [`deploy/`](../deploy/).

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
git push origin main

# no servidor
sudo /opt/ticketflow/update.sh
sudo systemctl restart ticketflow    # o worker reinicia junto
curl -fsS https://ticketflow.example.com/api/health
```

O `update.sh` da raiz do código busca a `main` do GitHub, instala as dependências (`uv sync --frozen`), gera o CSS das telas e aplica as migrações (`chamados db upgrade`). Chamado com `sudo`, ele roda como o usuário `ticketflow` (o dono do código). Não reinicia os serviços.

| Situação no servidor | `update.sh` | `update.sh --force` |
|----------------------|-------------|---------------------|
| Código igual a uma versão anterior da `main` | Atualiza | Atualiza |
| Arquivo do código alterado no servidor | Para e mostra os arquivos | Descarta a alteração e atualiza |
| Commit local, ou numa versão anterior por `git checkout <tag>` | Para e avisa | Volta para a `main` e atualiza |

Sem nada novo na `main`, as outras etapas rodam do mesmo jeito: rodar de novo refaz uma atualização que parou no meio (ex.: numa migração que falhou).

- Reiniciar os serviços é sempre um passo manual e consciente ([ADR 0010](adr/0010-producao-systemd.md)). Avisar a equipe antes: a interrupção dura poucos segundos.
- Cada versão traz notas de atualização ([12.5](12-processo-de-desenvolvimento.md#125-versões-e-entregas)). Ler antes de atualizar.

**Voltar à versão anterior:** com o código ainda na versão nova, desfazer as migrações dela (`chamados db downgrade <revisão>`, como o usuário `ticketflow` e com o `/etc/ticketflow/env`); depois, em `/opt/ticketflow`, `sudo -u ticketflow git checkout <tag anterior>`, `cd backend && sudo -u ticketflow uv sync --frozen --no-dev`, `sudo -u ticketflow scripts/css.sh` (da raiz) e o reinício. Se a migração não puder ser desfeita, restaurar um backup do banco (18.5). O `update.sh --force` volta à `main` depois.

## 18.5 Backup

O TicketFlow não faz backup: quem administra o servidor cuida dele, com as ferramentas que já usa. O backup precisa ter o banco `chamados` (ex.: `pg_dump -Fc`) e o diretório de anexos `/var/lib/ticketflow/files`, **da mesma data**: anexos mais novos que o banco ficam órfãos e são ignorados.

## 18.6 Rotina e monitoramento

| O quê | Como | Frequência |
|-------|------|------------|
| Serviços no ar | `systemctl status ticketflow ticketflow-worker` ou `/api/health` (confere o banco) | Diária, ou por um monitor externo |
| Erros | `journalctl -u ticketflow -p warning --since today` | Semanal |
| Espaço em disco | `df -h /var/lib` | Mensal |
| Certificado | O `certbot` renova sozinho; conferir com `sudo certbot certificates` | Mensal |
| Atualizações do sistema | Automáticas (segurança); reiniciar o servidor quando `/var/run/reboot-required` existir | Mensal |

## 18.7 Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---------|----------------|-------------|
| Página "502 Bad Gateway" | Serviço da API parado | `systemctl status ticketflow`; ver o erro em `journalctl -u ticketflow -n 100` |
| E-mails não chegam | Worker parado ou SMTP errado | `systemctl status ticketflow-worker`; `journalctl -u ticketflow-worker` mostra `tarefa_vai_tentar_de_novo` e `tarefa_falhou` com o erro do SMTP; conferir `/etc/ticketflow/env` e reiniciar o `ticketflow` (o worker vai junto) depois de mudar |
| Upload falha com erro 413 | Limite do nginx menor que o do sistema | Ajustar `client_max_body_size` e recarregar o nginx |
| Todos foram desconectados | `SECRET_KEY` mudou ou o banco foi restaurado | Esperado; cada um entra de novo |
| Serviço não sobe depois de atualizar | Migração falhou ou dependência faltando | Ler o fim da saída do `update.sh`; voltar à versão anterior (18.4) |
| Disco cheio | Anexos | Conferir `/var/lib/ticketflow/files`; aumentar o disco |
| Navegador avisa que o site não é seguro | Certificado vencido | `sudo certbot renew` e recarregar o nginx |
