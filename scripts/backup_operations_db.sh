#!/bin/sh
set -eu

retention_days="${BACKUP_RETENTION_DAYS:-14}"
case "$retention_days" in
  ''|*[!0-9]*) echo "BACKUP_RETENTION_DAYS must be a positive integer" >&2; exit 2 ;;
esac

docker compose --env-file .env.production exec -T backend \
  python -m app.scripts.backup_operations \
  --directory /app/data/backups \
  --label daily \
  --daily "$retention_days" \
  --weekly 4 \
  --monthly 6

echo "SQLite backup completed and verified. Configure an encrypted off-host copy separately."
