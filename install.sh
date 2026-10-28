#!/usr/bin/env bash
# Instala o TicketFlow em produção num Ubuntu 24.04 novo (docs/18 §18.3, passos 2 a 9):
# PostgreSQL 17, uv, o código em /opt/ticketflow, /etc/ticketflow/env, os serviços systemd e o
# nginx com HTTPS por um certificado autoassinado. Roda como root, direto do GitHub:
#
#   curl -fsSLO https://raw.githubusercontent.com/0LB-i/ticketflow/main/install.sh
#   sudo bash install.sh [DOMINIO]     # sem DOMINIO: ticketflow.local
#
# O TicketFlow usa o fuso da máquina: numa máquina ainda em UTC, o script o troca para o FUSO
# (padrão America/Sao_Paulo; outro: sudo FUSO=America/Manaus bash install.sh).
#
# O domínio de verdade e o certificado definitivo (certbot ou o da empresa) se configuram depois,
# no nginx (/etc/nginx/sites-available/ticketflow) e no APP_BASE_URL do /etc/ticketflow/env.
#
# O código vem só com o que a produção usa: o checkout esparso deixa de fora os testes, o
# benchmark, a documentação de desenvolvimento e os scripts da máquina de desenvolvimento. O
# /opt/ticketflow continua um repositório git, e as atualizações seguem pelo deploy.sh (§18.4),
# que respeita o mesmo filtro.
# Pode rodar de novo: o que já existe (env, banco, certificado) é mantido; os serviços que já
# estão no ar não são reiniciados.
set -euo pipefail

REPO=https://github.com/0LB-i/ticketflow.git
DESTINO=/opt/ticketflow # o caminho das units do systemd
ENV_FILE=/etc/ticketflow/env
TLS_DIR=/etc/ticketflow/tls
SERVICO=ticketflow
# O que não vai para o servidor (sintaxe do .gitignore).
FORA_DA_PRODUCAO=(
  /TAREFAS.md /ARCHITECTURE.md /CLAUDE.md /.claude/ /docs/
  /backend/tests/ /backend/bench/ /backend/.env.example
  /scripts/check.sh /scripts/install-hooks.sh /scripts/instalar-servico-dev.sh
  /scripts/preparar-maquina-dev.sh /scripts/vendor-tiptap.sh
)

if [[ $# -gt 1 ]]; then
  echo "uso: sudo bash $0 [DOMINIO]   (padrão: ticketflow.local)" >&2
  exit 2
fi
DOMINIO="${1:-ticketflow.local}"
FUSO="${FUSO:-America/Sao_Paulo}"
IP="$(hostname -I | awk '{print $1}')"

etapa() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
como_servico() { sudo -u "$SERVICO" -H bash -c "$1"; }

[[ $EUID -eq 0 ]] || { echo "Rode como root (sudo)." >&2; exit 1; }
# shellcheck disable=SC1091
. /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] ||
  echo "Aviso: feito para Ubuntu 24.04; esta máquina é $PRETTY_NAME." >&2
export DEBIAN_FRONTEND=noninteractive

etapa "pacotes básicos"
apt-get update -q
apt-get install -y -q --no-upgrade git curl ca-certificates gnupg nginx openssl

etapa "fuso horário"
# Telas, relatórios e rotinas usam o fuso da máquina (core/timezone.py); um fuso já escolhido
# por quem administra o servidor fica como está.
if [[ "$(timedatectl show -p Timezone --value)" =~ ^(Etc/)?UTC$ ]]; then
  timedatectl set-timezone "$FUSO"
fi
timedatectl show -p Timezone --value

etapa "usuário e diretórios"
id "$SERVICO" >/dev/null 2>&1 ||
  adduser --system --group --home /var/lib/ticketflow "$SERVICO"
install -d -o "$SERVICO" -g "$SERVICO" -m 750 /var/lib/ticketflow /var/lib/ticketflow/files
install -d -o root -g "$SERVICO" -m 750 /etc/ticketflow

etapa "PostgreSQL 17 (repositório oficial do PostgreSQL)"
if [[ ! -f /etc/apt/sources.list.d/pgdg.sources && ! -f /etc/apt/sources.list.d/pgdg.list ]]; then
  apt-get install -y -q --no-upgrade postgresql-common
  /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
fi
apt-get install -y -q --no-upgrade postgresql-17
# Autenticação peer: o usuário ticketflow do sistema entra como o papel ticketflow, sem senha.
[[ -n "$(sudo -u postgres psql -Atc "SELECT 1 FROM pg_roles WHERE rolname = '$SERVICO'")" ]] ||
  sudo -u postgres createuser "$SERVICO"
[[ -n "$(sudo -u postgres psql -Atc "SELECT 1 FROM pg_database WHERE datname = 'chamados'")" ]] ||
  sudo -u postgres createdb -O "$SERVICO" chamados

etapa "uv (Python)"
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi
uv --version

etapa "código em $DESTINO (só o que a produção usa)"
if [[ ! -d "$DESTINO/.git" ]]; then
  install -d -o "$SERVICO" -g "$SERVICO" -m 755 "$DESTINO"
  como_servico "git clone -q --no-checkout $REPO '$DESTINO'"
fi
como_servico "cd '$DESTINO' && git sparse-checkout set --no-cone '/*' $(printf "'!%s' " "${FORA_DA_PRODUCAO[@]}") && git checkout -q main"

etapa "configuração ($ENV_FILE)"
if [[ -f "$ENV_FILE" ]]; then
  echo "já existe: mantida como está"
else
  cat >"$ENV_FILE" <<FIM
# Produção (criado pelo install.sh; docs/18 §18.3, passo 6).
APP_BASE_URL=https://$DOMINIO
DATABASE_URL=postgresql+psycopg://$SERVICO@/chamados?host=/var/run/postgresql
FILES_DIR=/var/lib/ticketflow/files
# E-mail: sem SMTP_HOST, os e-mails vão para o log (journalctl -u $SERVICO-worker) e a tela de
# usuários mostra os links de convite. Depois de preencher: sudo systemctl restart $SERVICO
SMTP_HOST=
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM="TicketFlow <ticketflow@$DOMINIO>"
FIM
  chown root:"$SERVICO" "$ENV_FILE"
  chmod 640 "$ENV_FILE"
  echo "criado"
fi

etapa "dependências, CSS e migrações (scripts/deploy.sh)"
como_servico "$DESTINO/scripts/deploy.sh" >/dev/null

etapa "serviços systemd"
cp "$DESTINO"/deploy/ticketflow*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable -q "$SERVICO" "$SERVICO-worker"
if systemctl is-active -q "$SERVICO"; then
  echo "O serviço já estava rodando. Para colocar a versão nova no ar (o worker reinicia junto):"
  echo "  sudo systemctl restart $SERVICO"
else
  systemctl start "$SERVICO" "$SERVICO-worker"
  echo "Serviços iniciados."
fi

etapa "nginx nas portas 80 e 443 (certificado autoassinado)"
install -d -o root -g root -m 700 "$TLS_DIR"
if [[ ! -f "$TLS_DIR/ticketflow.crt" ]]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=$DOMINIO" \
    -addext "subjectAltName=DNS:$DOMINIO,DNS:$(hostname),IP:$IP" \
    -keyout "$TLS_DIR/ticketflow.key" -out "$TLS_DIR/ticketflow.crt" 2>/dev/null
  chmod 600 "$TLS_DIR/ticketflow.key"
  echo "certificado criado: $TLS_DIR/ticketflow.crt"
fi
# Os mesmos cabeçalhos do deploy/nginx.conf, menos o Strict-Transport-Security: com ele, o
# navegador não deixa seguir com o certificado autoassinado. Volta junto com o definitivo.
# Numa segunda rodada o arquivo é mantido (o domínio e o certificado se ajustam nele).
if [[ ! -f /etc/nginx/sites-available/$SERVICO ]]; then
  cat >/etc/nginx/sites-available/$SERVICO <<FIM
# Criado pelo install.sh, com certificado autoassinado. Para o domínio de verdade: trocar o
# server_name e o certificado (ou rodar o certbot --nginx -d DOMINIO), e o APP_BASE_URL do
# $ENV_FILE; com o certificado definitivo, acrescentar o Strict-Transport-Security.

upstream ticketflow {
    server 127.0.0.1:8000;
}

server {
    listen 80 default_server;
    server_name $DOMINIO;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2 default_server;
    server_name $DOMINIO;
    ssl_certificate     $TLS_DIR/ticketflow.crt;
    ssl_certificate_key $TLS_DIR/ticketflow.key;

    # Anexos de até 25 MB (docs/11 §11.3), com folga para o envio multipart.
    client_max_body_size 30m;

    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_read_timeout 60s;

    # Sem isto o nginx só comprime HTML (o JavaScript da interface vai inteiro).
    gzip on;
    gzip_proxied any;
    gzip_comp_level 5;
    gzip_types text/css text/javascript application/javascript application/json image/svg+xml;

    location / {
        proxy_pass http://ticketflow;

        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "same-origin" always;
        add_header X-Frame-Options "DENY" always;
        add_header Content-Security-Policy "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;
    }

    # A documentação interativa da API (Swagger) carrega scripts de uma CDN: sem a CSP restrita.
    location = /api/docs {
        proxy_pass http://ticketflow;
        add_header X-Content-Type-Options "nosniff" always;
    }
}
FIM
fi
ln -sf /etc/nginx/sites-available/$SERVICO /etc/nginx/sites-enabled/$SERVICO
rm -f /etc/nginx/sites-enabled/default
nginx -t -q
systemctl enable -q --now nginx
systemctl reload nginx
if ufw status 2>/dev/null | grep -q '^Status: active'; then
  ufw allow 'Nginx Full' >/dev/null
fi

cat <<FIM

TicketFlow instalado em $DESTINO, versão $(git -C "$DESTINO" describe --tags --always).
  endereço:     https://$DOMINIO ou https://$IP (documentação da API em /api/docs)
  certificado:  $TLS_DIR/ticketflow.crt, autoassinado (o navegador avisa até ser trocado)
  configuração: $ENV_FILE (preencha o SMTP para os e-mails saírem)
  domínio:      server_name e certificado em /etc/nginx/sites-available/$SERVICO, e o
                APP_BASE_URL em $ENV_FILE (os links dos e-mails); depois:
                sudo systemctl reload nginx && sudo systemctl restart $SERVICO
  estado:       systemctl status $SERVICO $SERVICO-worker
  log:          journalctl -u $SERVICO -u $SERVICO-worker -f
  atualizar:    sudo -u $SERVICO $DESTINO/scripts/deploy.sh && sudo systemctl restart $SERVICO

LOGO EM SEGUIDA entre com admin / admin e troque a senha: até lá, qualquer pessoa que alcance o
servidor entra como administrador (docs/18 §18.3, passo 10).
O uvicorn sobe com 4 workers, para 8 núcleos; esta máquina tem $(nproc) (docs/18 §18.3, passo 8).
FIM
