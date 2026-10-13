#!/bin/sh
# Nightly dump of the finode database (the "public" schema: every person's
# books and settings). Runs inside the postgres image, see compose.yaml.
#
#   BACKUP_DIR        where files go (default /backups)
#   BACKUP_KEEP_DAYS  how long to keep them (default 14)
#   BACKUP_HOUR       hour (UTC, 0-23) of the nightly run (default 2)
#   BACKUP_ONCE=1     dump once and exit (used to test)
#
# Logins live in Supabase Auth (not in this dump); Supabase keeps those.
set -eu

dir="${BACKUP_DIR:-/backups}"
keep="${BACKUP_KEEP_DAYS:-14}"
hour="${BACKUP_HOUR:-2}"

# FINODE_DATABASE_URL is a SQLAlchemy URL (postgresql+psycopg://...); pg_dump wants postgresql://.
url=$(printf '%s' "${FINODE_DATABASE_URL:?FINODE_DATABASE_URL is not set}" | sed -E 's#^([a-z]+)\+[a-z0-9]+://#\1://#')

dump() {
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    tmp="$dir/.finode-$stamp.sql.gz.partial"
    out="$dir/finode-$stamp.sql.gz"
    if pg_dump --schema=public --no-owner --no-privileges --dbname="$url" | gzip -9 > "$tmp" \
        && gzip -t "$tmp" \
        && [ "$(gzip -dc "$tmp" | grep -c '^CREATE TABLE public.transactions ')" -ge 1 ]; then
        mv "$tmp" "$out"
        echo "backup ok: $out ($(wc -c < "$out") bytes)"
        find "$dir" -name 'finode-*.sql.gz' -mtime "+$keep" -delete
    else
        rm -f "$tmp"
        echo "backup FAILED at $stamp" >&2
        return 1
    fi
}

mkdir -p "$dir"
if [ "${BACKUP_ONCE:-}" = 1 ]; then dump; exit; fi

while true; do
    # Seconds until the next HH:00 UTC.
    now=$(date -u +%s)
    today=$(date -u -d "today 00:00" +%s 2>/dev/null || echo $((now - now % 86400)))
    next=$((today + hour * 3600))
    [ "$next" -le "$now" ] && next=$((next + 86400))
    sleep $((next - now))
    dump || true
done
