#!/bin/sh
# Start StateChecker: wait for MongoDB, create the database on first start,
# then serve with gunicorn. Replaces upstream's start.sh, which started Apache,
# cron and MongoDB inside the container and built the UI on first boot.
set -eu

status() { printf '(%s) %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$1" > "$STATUS_FILE"; echo "statechecker: $1"; }

rm -f "$STARTED_FILE"
mkdir -p "$DATA_DIR" "$TMP_DIR" "$LOG_DIR"

# The first admin's password. setup_db.py would otherwise prompt for it on a
# terminal that does not exist and hang; and upstream's default is "cisco".
if [ -z "${DEFAULT_PASSWORD:-}" ]; then
    echo "statechecker: DEFAULT_PASSWORD is not set; refusing to create an admin with a default password" >&2
    exit 1
fi

status "waiting for the database"
tries=0
until python -m app.models.aci.worker --check_db >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [ "$tries" -ge 60 ]; then
        status "error: no database after $tries attempts"
        exit 1
    fi
    sleep 2
done

# Idempotent: only a database without users and settings is initialised, so the
# admin password is set once and later changes in the app are kept.
# --no_https: TLS ends at the appliance's proxy, which sets X-Forwarded-Proto.
status "initializing db"
python setup_db.py --no_https --app_name StateChecker --stdout

: > "$STARTED_FILE"
status "running"

# Snapshots and comparisons run in background processes of their own, so the
# web side stays small: two processes, eight threads each. Sessions live in
# MongoDB, so any process can serve any request. A long timeout for uploads.
exec gunicorn --bind 0.0.0.0:8080 --workers 2 --threads 8 --timeout 300 \
    --forwarded-allow-ips '*' --access-logfile - --error-logfile - wsgi:application
