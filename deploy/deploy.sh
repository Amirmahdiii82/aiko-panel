#!/usr/bin/env bash
# Install a release tarball into /opt/aiko-panel and restart the app.
# Usage: deploy.sh <release.tgz> <commit>
#
# Safety: databases are snapshotted before the release (migrations only move forward), and if the new
# version does not become healthy the previous code AND the snapshot are put back.
set -euo pipefail

TARBALL=$1
COMMIT=${2:-unknown}
ROOT=${AIKO_ROOT:-/opt/aiko-panel}
SERVICE=${AIKO_SERVICE:-aiko-panel}
PORT=$(grep -E '^PORT=' "$ROOT/.env" 2>/dev/null | cut -d= -f2 || true)
PORT=${PORT:-8020}
PREV=$ROOT/.previous
SNAP=$ROOT/data/backups/predeploy-$(date +%Y%m%d-%H%M%S)-${COMMIT:0:7}
KEEP=(--exclude .env --exclude data/ --exclude .venv/ --exclude .previous/ --exclude .deployed)
PY=$ROOT/.venv/bin/python
RUN_AS=${AIKO_USER:-aiko}
# app commands run as the service user so files in data/ keep the right owner
as_app() { if id "$RUN_AS" &>/dev/null; then runuser -u "$RUN_AS" -- "$@"; else "$@"; fi; }
fix_owner() { if id "$RUN_AS" &>/dev/null; then chown -R "$RUN_AS:$RUN_AS" "$ROOT/data"; fi; }

echo "==> deploying $COMMIT"
STAGE=$(mktemp -d)
# mktemp makes the folder 0700, and `rsync -a "$STAGE/" "$ROOT/"` copies the folder's own mode onto $ROOT:
# the service user could then no longer enter /opt/aiko-panel at all
chmod 755 "$STAGE"
trap 'rm -rf "$STAGE"' EXIT
tar -xzf "$TARBALL" -C "$STAGE"
old_webhook=$(sha256sum "$ROOT/deploy/webhook.py" 2>/dev/null | cut -d' ' -f1 || true)
PREV_DEPLOYED=$(cat "$ROOT/.deployed" 2>/dev/null || true)

echo "==> snapshot of the databases -> $SNAP"
if [[ -f $ROOT/data/core.db ]]; then
  (cd "$ROOT" && as_app "$PY" -m app backup "$SNAP" >/dev/null)
fi

echo "==> backing up current release"
mkdir -p "$PREV"
rsync -a --delete "${KEEP[@]}" "$ROOT/" "$PREV/"

echo "==> syncing files"
rsync -a --delete "${KEEP[@]}" "$STAGE/" "$ROOT/"

echo "==> installing dependencies"
"$ROOT/.venv/bin/pip" install -q --disable-pip-version-check -r "$ROOT/requirements.txt"

rollback() {
  echo "!! $1; rolling back"
  journalctl -u "$SERVICE" -n 40 --no-pager -o cat || true
  systemctl stop "$SERVICE" || true
  rsync -a --delete "${KEEP[@]}" "$PREV/" "$ROOT/"
  if [[ -n $PREV_DEPLOYED ]]; then echo "$PREV_DEPLOYED" > "$ROOT/.deployed"; fi
  if [[ -d $SNAP ]]; then
    for f in "$SNAP"/*.db; do
      name=$(basename "$f")
      rm -f "$ROOT/data/$name-wal" "$ROOT/data/$name-shm"
      cp "$f" "$ROOT/data/$name"
    done
    fix_owner
  fi
  "$ROOT/.venv/bin/pip" install -q --disable-pip-version-check -r "$ROOT/requirements.txt" || true
  systemctl start "$SERVICE"
  exit 1
}

echo "==> migrating databases"
(cd "$ROOT" && as_app "$PY" -m app migrate) || rollback "migration failed"

echo "==> restarting app"
echo "$COMMIT $(date -Is)" > "$ROOT/.deployed"
systemctl restart "$SERVICE"

healthy=0
for _ in $(seq 1 30); do
  sleep 1
  if curl -fsS "http://127.0.0.1:$PORT/healthz" | grep -q '"ok":true'; then healthy=1; break; fi
done
[[ $healthy == 1 ]] || rollback "app did not become healthy"

# keep the last 5 pre-deploy snapshots
ls -1d "$ROOT"/data/backups/predeploy-* 2>/dev/null | sort | head -n -5 | xargs -r rm -rf
echo "==> ok: $COMMIT is live"

# pick up changes to the receiver itself once this response has been sent
if [[ $(sha256sum "$ROOT/deploy/webhook.py" | cut -d' ' -f1) != "$old_webhook" ]]; then
  systemd-run --quiet --on-active=5 systemctl restart "$SERVICE-deploy" || true
fi
