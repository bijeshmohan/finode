#!/usr/bin/env bash
# Build the React app's own image (frontend/Dockerfile, the `web` service in compose.yaml) and check what it serves:
# every app address opens the app, a missing script is a 404 and never the page, the page and the service worker are
# never kept long while hashed files are kept a year, the headers, the API address built in, and nothing secret.
# Needs Docker. Usage: scripts/check-web-image.sh [API address, default https://finode.bijesh.me]
set -euo pipefail

API="${1:-https://finode.bijesh.me}"
IMAGE="finode-web:check"
NAME="finode-web-check-$$"

cd "$(dirname "$0")/.."

docker build -q -t "$IMAGE" --build-arg "VITE_API_URL=$API" -f frontend/Dockerfile . >/dev/null
# Listens on this machine only, on a port Docker picks.
docker run -d --rm --name "$NAME" -p 127.0.0.1::80 "$IMAGE" >/dev/null
trap 'docker stop "$NAME" >/dev/null 2>&1 || true' EXIT
PORT=$(docker port "$NAME" 80/tcp | head -1 | sed 's/.*://')
BASE="http://127.0.0.1:$PORT"
for _ in $(seq 1 30); do curl -fs -o /dev/null "$BASE/" && break; sleep 0.2; done

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# The status, then the headers in lower case, of one address.
head_of() { curl -s -o /dev/null -D - "$BASE$1" | tr -d '\r' | tr 'A-Z' 'a-z'; }
status_of() { curl -s -o /dev/null -w '%{http_code}' "$BASE$1"; }
expect_header() { # path, header line (lower case, a prefix of it)
  head_of "$1" | grep -q "^$2" || fail "$1 lacks '$2'"
}

page=$(curl -fs "$BASE/") || fail "/ did not answer"
[ "$(status_of /)" = 200 ] || fail "/ is not 200"
expect_header / "content-type: text/html"
expect_header / "cache-control: no-cache"

for path in "/accounts/00000000-0000-4000-8000-000000000001" "/oauth/consent?authorization_id=x" "/profile/data"; do
  [ "$(status_of "$path")" = 200 ] || fail "$path is not 200"
  [ "$(curl -fs "$BASE$path")" = "$page" ] || fail "$path is not the app's page"
  expect_header "$path" "cache-control: no-cache"
done

script=$(printf '%s' "$page" | grep -o '/assets/[^"]*\.js' | head -1)
[ -n "$script" ] || fail "the page names no script"
[ "$(status_of "$script")" = 200 ] || fail "$script is not 200"
head_of "$script" | grep -Eq "^content-type: (application|text)/javascript" || fail "$script is not JavaScript"
expect_header "$script" "cache-control: public, max-age=31536000, immutable"

[ "$(status_of /assets/missing-0000.js)" = 404 ] || fail "a missing script is not a 404"
if curl -s "$BASE/assets/missing-0000.js" | grep -qi "<!doctype html"; then fail "a missing script answers the app's page"; fi

for path in /sw.js /registerSW.js /manifest.webmanifest; do
  [ "$(status_of "$path")" = 200 ] || fail "$path is not 200"
  expect_header "$path" "cache-control: no-cache"
done
expect_header /manifest.webmanifest "content-type: application/manifest+json"

for path in / /profile/data "$script" /sw.js /assets/missing-0000.js; do
  expect_header "$path" "x-content-type-options: nosniff"
  expect_header "$path" "referrer-policy: same-origin"
done
if head_of / | grep -q "^server: nginx/"; then fail "the server names its version"; fi

# The API address reached the bundle; nothing secret did.
docker exec "$NAME" grep -rqF "$API" /usr/share/nginx/html/assets || fail "the app does not call $API"
for secret in supabase_service_role_key SUPABASE_SERVICE_ROLE_KEY sb_secret_ FINODE_DATABASE_URL postgresql+psycopg; do
  if docker exec "$NAME" grep -rqF "$secret" /usr/share/nginx/html; then fail "the image carries '$secret'"; fi
done

echo "web image: all checks passed ($API)"
