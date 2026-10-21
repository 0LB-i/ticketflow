#!/usr/bin/env bash
# Instala o TicketFlow como serviço systemd na máquina de desenvolvimento, em modo dev, em
# https://IP (o nginx nas portas 443 e 80, que redireciona para o HTTPS). Sem build e sem
# reiniciar a cada mudança:
#   - ticketflow.service: a unit da produção com o uvicorn em 127.0.0.1:8001 e --reload
#     (reinicia sozinho quando um .py muda); o nginx manda tudo para ele (a API e as telas);
#   - ticketflow-css.service: gera o CSS das telas do servidor (Tailwind) a cada mudança nos
#     templates (ADR 0011);
#   - mailpit.service: recebe os e-mails do sistema (SMTP em 127.0.0.1:1025) e os mostra em
#     http://IP:8025; nenhum e-mail sai da máquina.
# Instalações anteriores tinham também a interface pelo Vite (ticketflow-frontend.service),
# que saiu com a SPA: o script a desativa e apaga.
# Sem domínio, o certificado é autoassinado para o IP e o nome da máquina: o navegador avisa
# até ele ser instalado como confiável (/etc/ticketflow/tls/ticketflow.crt).
# Roda como root:
#   sudo scripts/instalar-servico-dev.sh
# Pode ser rodado de novo para atualizar dependências e aplicar migrações. Na primeira vez os
# serviços são iniciados; depois disso, quem reinicia é você.
set -euo pipefail
cd "$(dirname "$0")/.."

[[ $EUID -eq 0 ]] || { echo "Rode como root (sudo)." >&2; exit 1; }

IP="$(hostname -I | awk '{print $1}')"
API_PORTA=8001 # só local, atrás do nginx
TLS_DIR=/etc/ticketflow/tls
ENV_FILE=/etc/ticketflow/env
SERVICO=ticketflow
DROPIN_DIR="/etc/systemd/system/$SERVICO.service.d"
MAILPIT_VERSAO=v1.31.4
MAILPIT_SHA256=30942c4605c2ca8b9f759b1bb4e3ab6a12bdfdf66e5c94644ec2c75ac41e88e7

etapa() { printf '\n== %s\n' "$*"; }
# Dependências e compilação como o dono do código, para não deixar arquivos de root nele.
DONO="$(stat -c %U .)"
como_dono() {
  if [[ "$DONO" == root ]]; then
    bash -c "$1"
  else
    sudo -u "$DONO" -H bash -c "$1"
  fi
}

etapa "usuário e diretórios (docs/18 §18.3, passo 2)"
id "$SERVICO" >/dev/null 2>&1 ||
  adduser --system --group --home /var/lib/ticketflow "$SERVICO"
install -d -o "$SERVICO" -g "$SERVICO" -m 750 /var/lib/ticketflow /var/lib/ticketflow/files
install -d -o root -g "$SERVICO" -m 750 /etc/ticketflow

etapa "configuração ($ENV_FILE)"
if [[ -f "$ENV_FILE" ]]; then
  echo "já existe: mantida como está"
else
  cat >"$ENV_FILE" <<FIM
# Desenvolvimento, com HTTPS autoassinado (criado por scripts/instalar-servico-dev.sh).
DATABASE_URL=postgresql+psycopg://chamados:chamados@localhost:5432/chamados
LOG_FORMAT=console
LOG_LEVEL=INFO
APP_BASE_URL=https://$IP
COOKIE_SECURE=true
# Sem SMTP_HOST, os e-mails vão para o log: journalctl -u $SERVICO
FIM
  chown root:"$SERVICO" "$ENV_FILE"
  chmod 640 "$ENV_FILE"
  echo "criado"
fi
# Instalações antigas deste script não tinham HTTPS.
sed -i -e "s|^APP_BASE_URL=http://.*|APP_BASE_URL=https://$IP|" \
  -e "s|^# Sem HTTPS o navegador recusa cookies Secure.$||" \
  -e "s|^COOKIE_SECURE=false|COOKIE_SECURE=true|" "$ENV_FILE"
# Os e-mails vão para o Mailpit, a menos que já haja outro SMTP configurado.
if ! grep -q '^SMTP_HOST=' "$ENV_FILE"; then
  cat >>"$ENV_FILE" <<FIM
# Mailpit (scripts/instalar-servico-dev.sh): os e-mails aparecem em http://$IP:8025.
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_STARTTLS=false
FIM
  echo "e-mails pelo Mailpit"
fi

etapa "backend e migrações"
# Sem --no-dev: o mesmo ambiente roda os testes do scripts/check.sh.
como_dono "cd backend && uv sync -q --frozen"
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
(cd backend && .venv/bin/chamados db upgrade)

etapa "Mailpit $MAILPIT_VERSAO (e-mails de desenvolvimento)"
if ! /usr/local/bin/mailpit version 2>/dev/null | grep -q "$MAILPIT_VERSAO"; then
  tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/mailpit.tar.gz" \
    "https://github.com/axllent/mailpit/releases/download/$MAILPIT_VERSAO/mailpit-linux-amd64.tar.gz"
  echo "$MAILPIT_SHA256  $tmp/mailpit.tar.gz" | sha256sum -c --quiet
  tar -xzf "$tmp/mailpit.tar.gz" -C "$tmp" mailpit
  install -m 755 "$tmp/mailpit" /usr/local/bin/mailpit
  rm -rf "$tmp"
  echo "instalado em /usr/local/bin/mailpit"
fi
cat >/etc/systemd/system/mailpit.service <<FIM
# Só na máquina de desenvolvimento (scripts/instalar-servico-dev.sh): recebe os e-mails do
# TicketFlow e os mostra numa tela; nenhum sai da máquina.
[Unit]
Description=Mailpit (e-mails de desenvolvimento do TicketFlow)
After=network.target

[Service]
DynamicUser=yes
StateDirectory=mailpit
ExecStart=/usr/local/bin/mailpit --smtp 127.0.0.1:1025 --listen 0.0.0.0:8025 \
          --database /var/lib/mailpit/mailpit.db
Restart=on-failure

[Install]
WantedBy=multi-user.target
FIM
systemctl daemon-reload
systemctl enable -q --now mailpit

etapa "serviços systemd (modo de desenvolvimento)"
cp deploy/ticketflow.service /etc/systemd/system/
install -d "$DROPIN_DIR"
cat >"$DROPIN_DIR/desenvolvimento.conf" <<FIM
# Só na máquina de desenvolvimento (scripts/instalar-servico-dev.sh): atrás do nginx, e o
# uvicorn reinicia sozinho quando um .py muda.
[Service]
ExecStart=
ExecStart=$PWD/backend/.venv/bin/uvicorn chamados.main:create_app --factory \\
          --host 127.0.0.1 --port $API_PORTA --proxy-headers --forwarded-allow-ips 127.0.0.1 \\
          --reload --reload-dir $PWD/backend/src
FIM
cat >/etc/systemd/system/$SERVICO-css.service <<FIM
# Só na máquina de desenvolvimento (scripts/instalar-servico-dev.sh): o CSS das telas do
# servidor, gerado de novo a cada mudança nos templates (ADR 0011).
[Unit]
Description=TicketFlow (CSS das telas do servidor em modo de desenvolvimento, Tailwind)

[Service]
User=$DONO
ExecStart=$PWD/scripts/css.sh --watch
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
FIM
# A interface pelo Vite saiu com a SPA (ADR 0011).
if [[ -f /etc/systemd/system/$SERVICO-frontend.service ]]; then
  systemctl disable -q --now "$SERVICO-frontend" || true
  rm -f /etc/systemd/system/$SERVICO-frontend.service
  echo "$SERVICO-frontend (Vite) desativado e apagado"
fi
systemctl daemon-reload
systemctl enable -q "$SERVICO" "$SERVICO-css"
# Só inicia o do CSS (não faz nada se ele já estiver rodando); ele não afeta o outro.
systemctl start "$SERVICO-css"
if systemctl is-active -q "$SERVICO"; then
  echo "O serviço já estava rodando. Para usar a configuração nova:"
  echo "  sudo systemctl restart $SERVICO"
else
  systemctl start "$SERVICO"
  echo "Serviço iniciado."
fi

etapa "nginx nas portas 80 e 443 (certificado autoassinado)"
apt-get install -y -q --no-upgrade nginx openssl
install -d -o root -g root -m 700 "$TLS_DIR"
if [[ ! -f "$TLS_DIR/ticketflow.crt" ]]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=TicketFlow ($IP)" \
    -addext "subjectAltName=IP:$IP,DNS:$(hostname),DNS:localhost" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -keyout "$TLS_DIR/ticketflow.key" -out "$TLS_DIR/ticketflow.crt" 2>/dev/null
  chmod 600 "$TLS_DIR/ticketflow.key"
  echo "certificado criado: $TLS_DIR/ticketflow.crt"
fi
cat >/etc/nginx/sites-available/$SERVICO <<FIM
# Só na máquina de desenvolvimento (scripts/instalar-servico-dev.sh). A produção usa o
# deploy/nginx.conf, com o certificado do certbot.
server {
    listen 80 default_server;
    server_name _;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2 default_server;
    server_name _;
    ssl_certificate     $TLS_DIR/ticketflow.crt;
    ssl_certificate_key $TLS_DIR/ticketflow.key;

    # Anexos de até 25 MB (docs/11 §11.3), com folga para o envio multipart.
    client_max_body_size 30m;

    # Sem isto o nginx só comprime HTML: o CSS e o JavaScript (o Tiptap) iam inteiros.
    gzip on;
    gzip_proxied any;
    gzip_comp_level 5;
    gzip_types text/css text/javascript application/javascript application/json image/svg+xml;

    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "same-origin" always;
    add_header X-Frame-Options "DENY" always;

    # A API e as telas: tudo no uvicorn (ADR 0011).
    location / {
        proxy_pass http://127.0.0.1:$API_PORTA;
        proxy_read_timeout 60s;
    }
}
FIM
ln -sf /etc/nginx/sites-available/$SERVICO /etc/nginx/sites-enabled/$SERVICO
rm -f /etc/nginx/sites-enabled/default
nginx -t -q
systemctl enable -q --now nginx
systemctl reload nginx

cat <<FIM

TicketFlow em https://$IP (documentação da API em /api/docs)
  certificado: $TLS_DIR/ticketflow.crt (instale como confiável para o navegador não avisar)
  e-mails:     http://$IP:8025 (Mailpit)
  estado:      systemctl status $SERVICO $SERVICO-css mailpit nginx
  log:         journalctl -u $SERVICO -u $SERVICO-css -f
  Mudanças no código aparecem ao recarregar a página; migrações: cd backend && .venv/bin/chamados db upgrade
FIM
