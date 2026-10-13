#!/usr/bin/env bash
# Instala o TicketFlow como serviço systemd na máquina de desenvolvimento, sem nginx.
# Usa a mesma unit da produção (deploy/ticketflow.service) com um ajuste local
# (drop-in) para escutar na rede, em http://IP:PORTA. Roda como root:
#   sudo scripts/instalar-servico-dev.sh            # porta 8000
#   sudo PORTA=8080 scripts/instalar-servico-dev.sh
# Pode ser rodado de novo para recompilar e aplicar migrações. Na primeira vez o serviço é
# iniciado; depois disso, quem reinicia é você: sudo systemctl restart ticketflow
set -euo pipefail
cd "$(dirname "$0")/.."
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0

[[ $EUID -eq 0 ]] || { echo "Rode como root (sudo)." >&2; exit 1; }

PORTA="${PORTA:-8000}"
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

etapa "frontend (servido pelo próprio backend, ADR 0010)"
como_dono "cd frontend && pnpm install -s --frozen-lockfile && pnpm -s build"

etapa "serviço systemd"
cp deploy/ticketflow.service /etc/systemd/system/
install -d "$DROPIN_DIR"
cat >"$DROPIN_DIR/desenvolvimento.conf" <<FIM
# Só nesta máquina: sem nginx, o uvicorn escuta na rede (a produção usa 127.0.0.1 + nginx).
[Service]
ExecStart=
ExecStart=/opt/ticketflow/backend/.venv/bin/uvicorn chamados.main:create_app --factory --host 0.0.0.0 --port $PORTA
FIM
systemctl daemon-reload
systemctl enable -q "$SERVICO"
if systemctl is-active -q "$SERVICO"; then
  echo "O serviço já estava rodando. Para usar a versão nova: sudo systemctl restart $SERVICO"
else
  systemctl start "$SERVICO"
  echo "Serviço iniciado."
fi

cat <<FIM

TicketFlow em http://$IP:$PORTA (documentação da API em /api/docs)
  estado:    systemctl status $SERVICO
  log:       journalctl -u $SERVICO -f
  reiniciar: sudo systemctl restart $SERVICO
FIM
