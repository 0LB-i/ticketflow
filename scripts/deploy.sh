#!/usr/bin/env bash
# Atualiza a instalação no servidor (docs/18 §18.4). Roda como o usuário sistema-chamados:
#   sudo -u sistema-chamados /opt/sistema-chamados/scripts/deploy.sh
# Não reinicia os serviços: quem reinicia é o administrador (ADR 0010).
set -euo pipefail
cd "$(dirname "$0")/.."
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0

ENV_FILE="${ENV_FILE:-/etc/sistema-chamados/env}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/sistema-chamados}"
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

echo "== código"
git pull --ff-only

echo "== backend"
(cd backend && uv sync -q --frozen --no-dev)

echo "== frontend"
(cd frontend && pnpm install -s --frozen-lockfile && pnpm -s build)

echo "== backup do banco antes das migrações"
dump="$BACKUP_DIR/pre-deploy-$(date +%Y%m%d-%H%M%S).dump"
pg_dump -Fc -d "${DATABASE_URL/+psycopg/}" -f "$dump"
echo "salvo em $dump"

echo "== migrações"
(cd backend && .venv/bin/chamados db upgrade)

cat <<FIM

Pronto: versão $(git describe --tags --always) preparada.
Para colocar no ar, reinicie os serviços:
  sudo systemctl restart sistema-chamados sistema-chamados-worker
FIM
