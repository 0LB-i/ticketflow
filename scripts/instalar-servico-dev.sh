#!/usr/bin/env bash
# Instala o TicketFlow como serviço systemd na máquina de desenvolvimento, atrás do nginx.
# Usa a mesma unit da produção (deploy/ticketflow.service, uvicorn em 127.0.0.1:8000) e o
# deploy/nginx.conf, aceitando qualquer nome, em http://IP (porta 80). Roda como root:
#   sudo scripts/instalar-servico-dev.sh
# Pode ser rodado de novo para recompilar e aplicar migrações. Na primeira vez o serviço é
# iniciado; depois disso, quem reinicia é você: sudo systemctl restart ticketflow
set -euo pipefail
cd "$(dirname "$0")/.."
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0

[[ $EUID -eq 0 ]] || { echo "Rode como root (sudo)." >&2; exit 1; }

IP="$(hostname -I | awk '{print $1}')"
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
APP_BASE_URL=http://$IP
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

etapa "frontend (servido pelo próprio backend, ADR 0010)"
como_dono "cd frontend && pnpm install -s --frozen-lockfile && pnpm -s build"

etapa "serviço systemd"
cp deploy/ticketflow.service /etc/systemd/system/
# Instalações antigas deste script escutavam na rede, na porta 8000, com este ajuste local.
rm -f "$DROPIN_DIR/desenvolvimento.conf"
rmdir --ignore-fail-on-non-empty "$DROPIN_DIR" 2>/dev/null || true
systemctl daemon-reload
systemctl enable -q "$SERVICO"
if systemctl is-active -q "$SERVICO"; then
  echo "O serviço já estava rodando. Para usar a versão nova: sudo systemctl restart $SERVICO"
else
  systemctl start "$SERVICO"
  echo "Serviço iniciado."
fi

etapa "nginx (docs/18 §18.3, passo 9, sem HTTPS)"
apt-get install -y -q --no-upgrade nginx
# Sem domínio nesta máquina: atende por qualquer nome (o IP, por exemplo).
sed 's/^\(\s*server_name\) .*;/\1 _;/' deploy/nginx.conf >/etc/nginx/sites-available/$SERVICO
ln -sf /etc/nginx/sites-available/$SERVICO /etc/nginx/sites-enabled/$SERVICO
rm -f /etc/nginx/sites-enabled/default
nginx -t -q
systemctl enable -q --now nginx
systemctl reload nginx

cat <<FIM

TicketFlow em http://$IP (documentação da API em /api/docs)
  estado:    systemctl status $SERVICO
  log:       journalctl -u $SERVICO -f
  reiniciar: sudo systemctl restart $SERVICO
FIM
