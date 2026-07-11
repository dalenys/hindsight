# Substrate 0 — Phase 1: Postgres + pgvector on the Home Server

_Runbook for [`2026-04-21-substrate-0-design.md`](../../superpowers/specs/2026-04-21-substrate-0-design.md) Phase 1. Estimated effort: 30–45 min._

## Goal

Stand up Postgres 16 with the `pgvector` extension on the Ubuntu home server, bound so the Mac can reach it over Tailscale. This is infrastructure only; schema is Phase 2.

## Exit criterion

From the Mac, this command succeeds and returns one row with `vector` and a version:

```bash
psql "postgresql://hindsight:$DB_PASSWORD@<ubuntu-tailscale-ip>:5432/hindsight" \
  -c "select extname, extversion from pg_extension where extname='vector';"
```

## Prerequisites

- Ubuntu Server 22.04 LTS or 24.04 LTS with sudo access
- Tailscale running on both the Ubuntu box and the Mac (`tailscale status` shows both nodes)
- ~1 GB free disk on the Ubuntu box
- A password manager open and ready (1Password per your convention) to capture the DB password

## A. Verify Tailscale and capture the Ubuntu Tailscale IP

On the Ubuntu box:

```bash
tailscale status
tailscale ip -4
```

Record the `100.x.y.z` address. Call it `UBUNTU_TS_IP` for the rest of this runbook. If `tailscale status` shows the node as offline or expired, resolve that first — nothing else here works without it.

From the Mac:

```bash
tailscale ping <ubuntu-hostname>
```

A single ping reply confirms the mesh path before you commit to the DB install.

## B. Install Postgres 16 + pgvector (PGDG repo)

Use the PGDG apt repo rather than the Ubuntu default. Default Ubuntu 22.04 ships Postgres 14; PGDG gives you 16 consistently across 22.04 and 24.04 and is the supported path for `postgresql-16-pgvector`.

On the Ubuntu box:

```bash
sudo apt update
sudo apt install -y curl ca-certificates gnupg lsb-release

# Add PGDG repository
sudo install -d /usr/share/postgresql-common/pgdg
sudo curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
  https://www.postgresql.org/media/keys/ACCC4CF8.asc
sudo sh -c 'echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
sudo apt update

# Install
sudo apt install -y postgresql-16 postgresql-16-pgvector
```

Sanity check:

```bash
sudo -u postgres psql -c "select version();"
```

Expect `PostgreSQL 16.x ...`.

## C. Bind Postgres to Tailscale and restrict access

Edit `/etc/postgresql/16/main/postgresql.conf`:

```
listen_addresses = '*'
```

The wildcard is safe here because the server's only non-loopback interface reachable from anywhere meaningful is `tailscale0`. Defense-in-depth comes from `pg_hba.conf` + (optionally) UFW below.

Edit `/etc/postgresql/16/main/pg_hba.conf` and add this line near the bottom, above any broader rules:

```
# Tailscale mesh only — CGNAT range 100.64.0.0/10
host    all    all    100.64.0.0/10    scram-sha-256
```

Leave the default `local` and `127.0.0.1/32` lines alone so `sudo -u postgres psql` still works on the box itself.

Reload and restart:

```bash
sudo systemctl restart postgresql
sudo systemctl status postgresql --no-pager
```

If you run `ufw` (optional but good practice), pick the style that matches your existing host conventions:

```bash
# Interface-based (strictest — deny anything not arriving on tailscale0)
sudo ufw allow in on tailscale0 to any port 5432 proto tcp

# OR source-CIDR (matches existing Tailscale-service rules on most home servers)
sudo ufw allow from 100.64.0.0/10 to any port 5432 proto tcp comment 'Postgres hindsight Tailscale'
```

Both are redundant with `pg_hba.conf` but stop scans before they hit Postgres. Interface-based is marginally stricter (the interface-bind is a stronger guarantee than a CIDR match if Tailscale ever renumbers); source-CIDR reads more uniformly alongside other service rules. Pick one and be consistent across the box.

## D. Create the database, user, and extension

Generate a strong password now and save it to 1Password under `hindsight db / home server` (or your preferred item name). Example generator on either machine:

```bash
python3 -c "import secrets, string; print(''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(32)))"
```

Then on the Ubuntu box (paste the generated password into the single-quoted string):

```bash
sudo -u postgres psql <<'SQL'
create user hindsight with password 'PASTE_GENERATED_PASSWORD_HERE';
create database hindsight owner hindsight;
\c hindsight
create extension vector;
grant all privileges on database hindsight to hindsight;
SQL
```

Verify the extension is registered:

```bash
sudo -u postgres psql -d hindsight \
  -c "select extname, extversion from pg_extension where extname='vector';"
```

Expect one row, e.g. `vector | 0.8.0`.

## E. Verify from the Mac (exit criterion)

If `psql` isn't installed on the Mac:

```bash
brew install libpq
echo 'export PATH="/opt/homebrew/opt/libpq/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Capture the password into an env var for the session (don't paste it on the command line where it'll land in shell history):

```bash
read -s DB_PASSWORD && export DB_PASSWORD
# paste password, press Enter
```

Run the exit-criterion check. Keep the password in `PGPASSWORD` and pipe the query via stdin — avoids both `$DB_PASSWORD` substitution into argv (where `ps` could see it) and writing the URI-with-password to shell history:

```bash
echo "select extname, extversion from pg_extension where extname='vector';" | \
  PGPASSWORD="$DB_PASSWORD" psql "postgresql://hindsight@<UBUNTU_TS_IP>:5432/hindsight"
```

Expected output:

```
 extname | extversion
---------+------------
 vector  | 0.8.0
(1 row)
```

If you get that row, Phase 1 is complete.

## Troubleshooting

| Symptom                                   | Likely cause                                                     | Fix                                                                                                                     |
| ----------------------------------------- | ---------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `postgresql-16-pgvector` not found by apt | PGDG repo didn't attach                                          | Re-check `/etc/apt/sources.list.d/pgdg.list` content and signing key path                                               |
| `could not connect to server` from Mac    | `listen_addresses` not reloaded, or pg_hba denies                | Check `sudo tail -50 /var/log/postgresql/postgresql-16-main.log`; confirm your Mac's Tailscale IP is in `100.64.0.0/10` |
| `FATAL: password authentication failed`   | Password mismatch or quoting issue in SQL heredoc                | Re-run the `create user ... with password '...'` statement; confirm you're not pasting curly quotes                     |
| `extension "vector" is not available`     | Package installed but matched a different Postgres major version | Run `ls /usr/share/postgresql/16/extension/vector*` — the control file must exist there                                 |
| Mac can reach SSH but not 5432            | Host firewall (UFW) or router-level block                        | `sudo ufw status`; on the Ubuntu box, `sudo ss -tlnp sport = :5432` should show postgres bound on `0.0.0.0:5432`        |

## What to capture before moving to Phase 2

Record these four values — Phase 2 needs them:

1. **Ubuntu Tailscale IP** → will become `DB_HOST` in `.env`
2. **Postgres version** (e.g., 16.8) — Phase 2 schema assumes 16+ for `gen_random_uuid()` without the `pgcrypto` extension
3. **pgvector version** (from the exit-criterion query) — informs whether HNSW index syntax is available (yes from 0.5.0+)
4. **Password** stored in 1Password — Phase 2 ingester reads it from a chezmoi-generated `.env` file

## Known limitations carried forward

- **IPv6 Tailscale not admitted.** `pg_hba.conf` only whitelists `100.64.0.0/10` (IPv4 CGNAT). If a future client needs to connect over the IPv6 Tailscale mesh (`fd7a:115c:a1e0::/48`), add a second line: `host all all fd7a:115c:a1e0::/48 scram-sha-256`. For S0's Mac→Ubuntu path this doesn't matter; IPv4 is the default.
- **Reversibility.** The runbook's edits to `postgresql.conf` and `pg_hba.conf` should be backed up alongside the edit (e.g., `sudo cp postgresql.conf postgresql.conf.pre-s0` before editing). Full revert is `cp *.pre-s0` over the current files + `systemctl restart postgresql`.

## Anti-scope for Phase 1

- No schema, no tables (that's Phase 2)
- No TLS between Mac and Postgres — Tailscale provides WireGuard encryption in transit
- No replication, no PITR, no streaming backups — `pg_dump` on cron is the Phase 1+ backup posture per the brief
- No connection pooler (pgbouncer/pgcat) — direct connections are fine at S0 volumes
