#!/usr/bin/env bash
# Deploy the current commit from your own computer — the same signed release GitHub Actions sends, for when the
# server cannot be reached from abroad (GitHub's runners are outside Iran). Turn the VPN OFF first.
#
#   DEPLOY_SECRET=... bash deploy/push-release.sh            # secret: /etc/aiko-panel/deploy.env on the server
#   DEPLOY_URL=https://aiko.infinitcode.ir/__deploy (default)
#
# The server side is unchanged: snapshot → install → migrate → restart → health check → rollback on failure.
set -euo pipefail
: "${DEPLOY_SECRET:?set DEPLOY_SECRET (value from /etc/aiko-panel/deploy.env on the server)}"
URL=${DEPLOY_URL:-https://aiko.infinitcode.ir/__deploy}
cd "$(git rev-parse --show-toplevel)"
[[ -z $(git status --porcelain) ]] || { echo "commit your changes first (only committed code is deployed)"; exit 1; }
COMMIT=$(git rev-parse HEAD)

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir "$WORK/release"
git archive HEAD | tar -x -C "$WORK/release"
chmod 755 "$WORK/release"
tar --owner=0 --group=0 --numeric-owner -czf "$WORK/release.tgz" -C "$WORK/release" . 2>/dev/null \
  || tar -czf "$WORK/release.tgz" -C "$WORK/release" .          # macOS bsdtar has no --owner flags
sig="sha256=$(openssl dgst -sha256 -hmac "$DEPLOY_SECRET" -r "$WORK/release.tgz" | cut -d' ' -f1)"

echo "==> sending ${COMMIT:0:7} to $URL"
code=$(curl -sS --http1.1 --max-time 900 -o "$WORK/out.txt" -w '%{http_code}' -X POST --data-binary @"$WORK/release.tgz" \
  -H "Content-Type: application/gzip" -H "X-Signature: $sig" -H "X-Commit: $COMMIT" "$URL") || code=000
cat "$WORK/out.txt" 2>/dev/null || true
echo "HTTP $code"
[[ $code == 200 ]]
