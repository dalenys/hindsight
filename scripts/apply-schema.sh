#!/usr/bin/env bash
# Apply the Substrate 0 schema to the hindsight database.
#
# Reads DATABASE_URL from the environment. If unset, sources
# ~/.secrets/hindsight.env (chezmoi-generated per the project's
# credential convention). Errors loudly if neither is available.
#
# Idempotent — the schema file uses CREATE ... IF NOT EXISTS throughout.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SECRETS_FILE="${HOME}/.secrets/hindsight.env"
SCHEMA_FILE="$REPO_ROOT/schema/001_initial.sql"

if [[ -z "${DATABASE_URL:-}" && -f "$SECRETS_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$SECRETS_FILE"; set +a
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "error: DATABASE_URL not set and $SECRETS_FILE not found" >&2
  echo "       export DATABASE_URL=... or create the secrets file via chezmoi" >&2
  exit 1
fi

if [[ ! -f "$SCHEMA_FILE" ]]; then
  echo "error: schema file not found at $SCHEMA_FILE" >&2
  exit 1
fi

echo "Applying $SCHEMA_FILE"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$SCHEMA_FILE"
echo "Schema applied."
