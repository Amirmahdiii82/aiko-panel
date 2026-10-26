#!/usr/bin/env bash
# First-time installation of Aiko Panel on the Iran server (run as root, from the unpacked repo folder):
#
#   sudo bash deploy/bootstrap-server.sh
#
# What it does (each step is skipped if already done):
#   1. creates the `aiko` system user and /opt/aiko-panel with a Python venv
#   2. copies the code, writes .env from .env.example (edit it afterwards!)
#   3. creates the databases (restore a backup into /opt/aiko-panel/data first to move an existing panel)
#   4. installs the systemd units (app + deploy receiver) and the TCP MSS clamp
#   5. prints what is left: .env, the Caddy block, the GitHub deploy secret
set -euo pipefail

SRC=$(cd "$(dirname "$0")/.." && pwd)
ROOT=/opt/aiko-panel

[[ $EUID -eq 0 ]] || { echo "run as root (sudo)"; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required (3.10 or newer)"; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "python 3.10+ is required"; exit 1; }

echo "==> user and folders"
id aiko &>/dev/null || useradd --system --home "$ROOT" --shell /usr/sbin/nologin aiko
mkdir -p "$ROOT" "$ROOT/data" /etc/aiko-panel
rsync -a --exclude /.git --exclude /.venv --exclude /data --exclude /.env "$SRC/" "$ROOT/"

echo "==> python environment"
[[ -x $ROOT/.venv/bin/python ]] || python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -q --upgrade pip
"$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements.txt"

if [[ ! -f $ROOT/.env ]]; then
  echo "==> .env (from .env.example)"
  cp "$ROOT/.env.example" "$ROOT/.env"
  sed -i "s|^INITIAL_PASSWORD=.*|INITIAL_PASSWORD=$(head -c 12 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 12)|" "$ROOT/.env"
  echo "   first-login password for the owners: $(grep ^INITIAL_PASSWORD "$ROOT/.env" | cut -d= -f2)"
fi
chown root:aiko "$ROOT/.env" && chmod 640 "$ROOT/.env"

echo "==> databases"
(cd "$ROOT" && "$ROOT/.venv/bin/python" -m app migrate)
chown -R aiko:aiko "$ROOT/data"

echo "==> systemd"
cp "$ROOT/deploy/aiko-panel.service" "$ROOT/deploy/aiko-panel-deploy.service" /etc/systemd/system/
[[ -f /etc/systemd/system/tcp-mss-clamp.service ]] || cp "$ROOT/deploy/tcp-mss-clamp.service" /etc/systemd/system/
if [[ ! -f /etc/aiko-panel/deploy.env ]]; then
  echo "DEPLOY_SECRET=$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 40)" > /etc/aiko-panel/deploy.env
  chmod 600 /etc/aiko-panel/deploy.env
fi
systemctl daemon-reload
systemctl enable --now tcp-mss-clamp aiko-panel aiko-panel-deploy

sleep 3
PORT=$(grep -E '^PORT=' "$ROOT/.env" | cut -d= -f2)
curl -fsS "http://127.0.0.1:${PORT:-8020}/healthz" && echo

cat <<EOF

==> done. Next steps:
  1. edit $ROOT/.env (PUBLIC_URL, COOKIE_SECURE=1, ...) then: systemctl restart aiko-panel
  2. add the block from $ROOT/deploy/Caddyfile to /etc/caddy/Caddyfile (DNS of the domain → this server),
     then: systemctl reload caddy
  3. GitHub: repo secret DEPLOY_SECRET = value in /etc/aiko-panel/deploy.env,
     repo variable DEPLOY_URL = https://<panel domain>/__deploy
EOF
