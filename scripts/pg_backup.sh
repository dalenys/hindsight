#!/usr/bin/env bash
# Nightly pg_dump backup of the hindsight database.
#
# Runs under the deploy user on the home server (invoked by the
# accompanying systemd timer unit, see systemd/pg-backup.{service,timer}).
# Writes compressed custom-format dumps to ~/backups/hindsight/
# and keeps the last 14 days.
#
# Restore: pg_restore -d hindsight hindsight-YYYY-MM-DD.dump
#
# Intentionally simple: no offsite sync, no integrity check, no retention
# metrics. S0 data is disposable (~$0.20 + 15 min to re-embed) so a
# local-only dump is sufficient. Substrate 1+ will add offsite + checks.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/hindsight}"
DATABASE_URL="${DATABASE_URL:?DATABASE_URL must be set}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"

timestamp=$(date -u +%Y-%m-%d-%H%M%S)
outfile="$BACKUP_DIR/hindsight-$timestamp.dump"

# Custom format, max compression, stop on first error.
pg_dump --format=custom --compress=9 --file="$outfile" "$DATABASE_URL"

# Rotate: delete dumps older than RETENTION_DAYS.
find "$BACKUP_DIR" -name 'hindsight-*.dump' -type f -mtime "+$RETENTION_DAYS" -delete

# Emit one structured line for the systemd journal.
size=$(stat -c%s "$outfile" 2>/dev/null || stat -f%z "$outfile")
echo "pg_backup ok file=$outfile bytes=$size retention_days=$RETENTION_DAYS"
