#!/usr/bin/env bash
# Backup diário do banco e dos anexos (docs/18 §18.5). Rodado pelo ticketflow-backup.timer.
set -euo pipefail

ENV_FILE="${ENV_FILE:-/etc/ticketflow/env}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/ticketflow}"
RETENCAO_DIAS="${RETENCAO_DIAS:-14}"
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

dump="$BACKUP_DIR/db-$(date +%F).dump"
pg_dump -Fc -d "${DATABASE_URL/+psycopg/}" -f "$dump.tmp"
mv "$dump.tmp" "$dump"

mkdir -p "$BACKUP_DIR/files"
if [[ -d "${FILES_DIR:-}" ]]; then
  rsync -a --delete "$FILES_DIR/" "$BACKUP_DIR/files/"
fi

find "$BACKUP_DIR" -maxdepth 1 -name 'db-*.dump' -mtime +"$RETENCAO_DIAS" -delete
find "$BACKUP_DIR" -maxdepth 1 -name 'pre-deploy-*.dump' -mtime +"$RETENCAO_DIAS" -delete

# Cópia para fora do servidor (questão 13). Ex.: BACKUP_REMOTE=backup@nas:/backups/ticketflow
if [[ -n "${BACKUP_REMOTE:-}" ]]; then
  rsync -a --delete "$BACKUP_DIR/" "$BACKUP_REMOTE/"
else
  echo "AVISO: BACKUP_REMOTE não definido; o backup ficou só neste servidor." >&2
fi
echo "backup concluído: $dump"
