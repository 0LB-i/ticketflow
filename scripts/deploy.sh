#!/usr/bin/env bash
# Atualiza a instalação no servidor (docs/18 §18.4). Roda como o usuário ticketflow:
#   sudo -u ticketflow /opt/ticketflow/scripts/deploy.sh
# Não reinicia os serviços: quem reinicia é o administrador (ADR 0010).
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${ENV_FILE:-/etc/ticketflow/env}"
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

echo "== código"
git pull --ff-only

echo "== backend"
(cd backend && uv sync -q --frozen --no-dev)

echo "== CSS das telas do servidor"
scripts/css.sh

echo "== migrações"
(cd backend && .venv/bin/chamados db upgrade)

cat <<FIM

Pronto: versão $(git describe --tags --always) preparada.
Para colocar no ar, reinicie os serviços:
  sudo systemctl restart ticketflow ticketflow-worker
FIM
