#!/usr/bin/env bash
# Instala o TicketFlow como serviço systemd na máquina de desenvolvimento, em modo dev, em
# http://IP:8000. Sem build e sem reiniciar a cada mudança:
#   - ticketflow.service: a unit da produção com o uvicorn em 127.0.0.1:8001 e --reload
#     (reinicia sozinho quando um .py muda);
#   - ticketflow-frontend.service: o Vite na porta 8000, que compila sob demanda, atualiza o
#     navegador sozinho e repassa /api para o uvicorn.
# Roda como root:
#   sudo scripts/instalar-servico-dev.sh
# Pode ser rodado de novo para atualizar dependências e aplicar migrações. Na primeira vez os
# serviços são iniciados; depois disso, quem reinicia é você.
set -euo pipefail
cd "$(dirname "$0")/.."
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0

[[ $EUID -eq 0 ]] || { echo "Rode como root (sudo)." >&2; exit 1; }

IP="$(hostname -I | awk '{print $1}')"
PORTA=8000     # Vite, na rede
API_PORTA=8001 # uvicorn, só local
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
# Desenvolvimento, sem HTTPS (criado por scripts/instalar-servico-dev.sh).
DATABASE_URL=postgresql+psycopg://chamados:chamados@localhost:5432/chamados
LOG_FORMAT=console
LOG_LEVEL=INFO
APP_BASE_URL=http://$IP:$PORTA
# Sem HTTPS o navegador recusa cookies Secure.
COOKIE_SECURE=false
# Sem SMTP_HOST, os e-mails vão para o log: journalctl -u $SERVICO
FIM
  chown root:"$SERVICO" "$ENV_FILE"
  chmod 640 "$ENV_FILE"
  echo "criado"
fi

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
Environment=TF_API=http://127.0.0.1:$API_PORTA NO_COLOR=1
ExecStart=$PWD/frontend/node_modules/.bin/vite --host 0.0.0.0 --port $PORTA --strictPort
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
FIM
systemctl daemon-reload
systemctl enable -q "$SERVICO" "$SERVICO-frontend"
if systemctl is-active -q "$SERVICO"; then
  echo "O serviço já estava rodando. Para usar a configuração nova:"
  echo "  sudo systemctl restart $SERVICO $SERVICO-frontend"
else
  systemctl start "$SERVICO" "$SERVICO-frontend"
  echo "Serviços iniciados."
fi

# Instalações antigas deste script usavam o nginx na porta 80; o Vite atende direto.
if [[ -e /etc/nginx/sites-enabled/$SERVICO ]]; then
  rm -f /etc/nginx/sites-enabled/$SERVICO
  systemctl reload nginx
fi

cat <<FIM

TicketFlow em http://$IP:$PORTA (documentação da API em /api/docs)
  estado:    systemctl status $SERVICO $SERVICO-frontend
  log:       journalctl -u $SERVICO -u $SERVICO-frontend -f
  Mudanças no código aparecem sozinhas; migrações: cd backend && .venv/bin/chamados db upgrade
FIM
