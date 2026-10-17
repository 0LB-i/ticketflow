#!/usr/bin/env bash
# Instala o TicketFlow como serviço systemd na máquina de desenvolvimento, em modo dev, em
# https://IP (o nginx nas portas 443 e 80, que redireciona para o HTTPS). Sem build e sem
# reiniciar a cada mudança:
#   - ticketflow.service: a unit da produção com o uvicorn em 127.0.0.1:8001 e --reload
#     (reinicia sozinho quando um .py muda); o nginx manda /api para ele;
#   - ticketflow-frontend.service: o Vite em 127.0.0.1:5173, que compila sob demanda e
#     atualiza o navegador sozinho (websocket pelo nginx); o nginx manda o resto para ele;
#   - ticketflow-css.service: gera o CSS das telas do servidor (Tailwind) a cada mudança nos
#     templates (ADR 0011).
# Sem domínio, o certificado é autoassinado para o IP e o nome da máquina: o navegador avisa
# até ele ser instalado como confiável (/etc/ticketflow/tls/ticketflow.crt).
# Roda como root:
#   sudo scripts/instalar-servico-dev.sh
# Pode ser rodado de novo para atualizar dependências e aplicar migrações. Na primeira vez os
# serviços são iniciados; depois disso, quem reinicia é você.
set -euo pipefail
cd "$(dirname "$0")/.."
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0

[[ $EUID -eq 0 ]] || { echo "Rode como root (sudo)." >&2; exit 1; }

IP="$(hostname -I | awk '{print $1}')"
VITE_PORTA=5173 # só local, atrás do nginx
API_PORTA=8001  # só local, atrás do nginx
TLS_DIR=/etc/ticketflow/tls
ENV_FILE=/etc/ticketflow/env
SERVICO=ticketflow
DROPIN_DIR="/etc/systemd/system/$SERVICO.service.d"

etapa() { printf '\n== %s\n' "$*"; }
# Dependências e compilação como o dono do código, para não deixar arquivos de root nele.
DONO="$(stat -c %U .)"
como_dono() {
  if [[ "$DONO" == root ]]; then
    bash -c "$1"
  else
    sudo -u "$DONO" -H env COREPACK_ENABLE_DOWNLOAD_PROMPT=0 bash -c "$1"
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

etapa "backend e migrações"
# Sem --no-dev: o mesmo ambiente roda os testes do scripts/check.sh.
como_dono "cd backend && uv sync -q --frozen"
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
(cd backend && .venv/bin/chamados db upgrade)

etapa "frontend (só as dependências: o Vite compila sob demanda)"
como_dono "cd frontend && pnpm install -s --frozen-lockfile"

etapa "serviços systemd (modo de desenvolvimento)"
cp deploy/ticketflow.service /etc/systemd/system/
install -d "$DROPIN_DIR"
cat >"$DROPIN_DIR/desenvolvimento.conf" <<FIM
# Só na máquina de desenvolvimento (scripts/instalar-servico-dev.sh): atrás do Vite, e o
# uvicorn reinicia sozinho quando um .py muda.
[Service]
ExecStart=
ExecStart=$PWD/backend/.venv/bin/uvicorn chamados.main:create_app --factory \\
          --host 127.0.0.1 --port $API_PORTA --proxy-headers --forwarded-allow-ips 127.0.0.1 \\
          --reload --reload-dir $PWD/backend/src
FIM
cat >/etc/systemd/system/$SERVICO-frontend.service <<FIM
# Só na máquina de desenvolvimento (scripts/instalar-servico-dev.sh): a interface pelo Vite.
[Unit]
Description=TicketFlow (interface em modo de desenvolvimento, Vite)
After=network.target $SERVICO.service
Wants=$SERVICO.service

[Service]
User=$DONO
WorkingDirectory=$PWD/frontend
# O navegador abre o websocket da atualização automática pelo nginx, na 443. O Vite aceita
# o IP; o nome da máquina precisa ser liberado.
Environment=TF_HMR_PORT=443 NO_COLOR=1 __VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS=$(hostname)
ExecStart=$PWD/frontend/node_modules/.bin/vite --host 127.0.0.1 --port $VITE_PORTA --strictPort
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
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
systemctl daemon-reload
systemctl enable -q "$SERVICO" "$SERVICO-frontend" "$SERVICO-css"
# Só inicia o do CSS (não faz nada se ele já estiver rodando); ele não afeta os outros dois.
systemctl start "$SERVICO-css"
if systemctl is-active -q "$SERVICO"; then
  echo "O serviço já estava rodando. Para usar a configuração nova:"
  echo "  sudo systemctl restart $SERVICO $SERVICO-frontend"
else
  systemctl start "$SERVICO" "$SERVICO-frontend"
  echo "Serviços iniciados."
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
map \$http_upgrade \$tf_connection {
    default upgrade;
    ''      close;
}

server {
    listen 80 default_server;
    server_name _;
    return 301 https://\$host\$request_uri;
}

server {
    # HTTP/2: o Vite manda cada módulo num arquivo separado (centenas por tela); no HTTP/1.1
    # o navegador baixa só seis por vez.
    listen 443 ssl http2 default_server;
    server_name _;
    ssl_certificate     $TLS_DIR/ticketflow.crt;
    ssl_certificate_key $TLS_DIR/ticketflow.key;

    # Anexos de até 25 MB (docs/11 §11.3), com folga para o envio multipart.
    client_max_body_size 30m;

    # Sem isto o nginx só comprime HTML: o JavaScript do modo dev (~19 MB) ia inteiro.
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

    location /api/ {
        proxy_pass http://127.0.0.1:$API_PORTA;
        proxy_read_timeout 60s;
    }

    # Interface pelo Vite, com o websocket da atualização automática.
    location / {
        proxy_pass http://127.0.0.1:$VITE_PORTA;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$tf_connection;
        proxy_read_timeout 1h;
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
  estado:      systemctl status $SERVICO $SERVICO-frontend $SERVICO-css nginx
  log:         journalctl -u $SERVICO -u $SERVICO-frontend -u $SERVICO-css -f
  Mudanças no código aparecem sozinhas; migrações: cd backend && .venv/bin/chamados db upgrade
FIM
