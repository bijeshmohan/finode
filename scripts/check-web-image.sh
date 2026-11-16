#!/usr/bin/env bash
# Build the React app's own image (frontend/Dockerfile, the `web` service in compose.yaml) and check what it serves:
# every app address opens the app, a missing script is a 404 and never the page, the page and the service worker are
# never kept long while hashed files are kept a year, the headers, the API address built in, and nothing secret. It runs
# the container as compose.yaml does (read-only, no capabilities, no new privileges), as the user the image names.
# Needs Docker. Usage: scripts/check-web-image.sh [API address, default https://finode.bijesh.me]
set -euo pipefail

API="${1:-https://finode.bijesh.me}"
IMAGE="finode-web:check"
NAME="finode-web-check-$$"

cd "$(dirname "$0")/.."

docker build -q -t "$IMAGE" --build-arg "VITE_API_URL=$API" -f frontend/Dockerfile . >/dev/null
# Listens on this machine only, on a port Docker picks; restricted as the `web` service is in compose.yaml.
docker run -d --rm --name "$NAME" -p 127.0.0.1::8080 \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true "$IMAGE" >/dev/null
trap 'docker stop "$NAME" >/dev/null 2>&1 || true' EXIT
PORT=$(docker port "$NAME" 8080/tcp | head -1 | sed 's/.*://')
BASE="http://127.0.0.1:$PORT"
for _ in $(seq 1 30); do curl -fs -o /dev/null "$BASE/" && break; sleep 0.2; done

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# The headers in lower case of one address (read whole first: a pipe into `grep -q` can end in SIGPIPE under pipefail).
head_of() {
  local headers
  headers=$(curl -s -o /dev/null -D - "$BASE$1")
  printf '%s\n' "$headers" | tr -d '\r' | tr 'A-Z' 'a-z'
}
status_of() { curl -s -o /dev/null -w '%{http_code}' "$BASE$1"; }
has_line() { # text, pattern (extended)
  printf '%s\n' "$1" | grep -Eq "$2"
}
expect_header() { # path, header line (lower case, a prefix of it; a basic pattern, so "+" is itself)
  printf '%s\n' "$(head_of "$1")" | grep -q "^$2" || fail "$1 lacks '$2'"
}

# Not root, and a health check Docker can run.
[ "$(docker exec "$NAME" id -u)" != 0 ] || fail "nginx runs as root"
[ -n "$(docker inspect --format '{{if .Config.Healthcheck}}{{.Config.Healthcheck.Test}}{{end}}' "$IMAGE")" ] ||
  fail "the image has no health check"

page=$(curl -fs "$BASE/") || fail "/ did not answer"
[ "$(status_of /)" = 200 ] || fail "/ is not 200"
expect_header / "content-type: text/html"
expect_header / "cache-control: no-cache"

for path in "/accounts/00000000-0000-4000-8000-000000000001" "/oauth/consent?authorization_id=x" "/profile/data"; do
  [ "$(status_of "$path")" = 200 ] || fail "$path is not 200"
  [ "$(curl -fs "$BASE$path")" = "$page" ] || fail "$path is not the app's page"
  expect_header "$path" "cache-control: no-cache"
done

script=$(printf '%s' "$page" | grep -o '/assets/[^"]*\.js' | head -1 || true)
[ -n "$script" ] || fail "the page names no script"
[ "$(status_of "$script")" = 200 ] || fail "$script is not 200"
has_line "$(head_of "$script")" "^content-type: (application|text)/javascript" || fail "$script is not JavaScript"
expect_header "$script" "cache-control: public, max-age=31536000, immutable"

[ "$(status_of /assets/missing-0000.js)" = 404 ] || fail "a missing script is not a 404"
if has_line "$(curl -s "$BASE/assets/missing-0000.js")" "<!(doctype|DOCTYPE) html"; then
  fail "a missing script answers the app's page"
fi
# An old service worker's workbox file, gone after a redeploy, is a 404 too, never the page.
[ "$(status_of /workbox-00000000.js)" = 404 ] || fail "a missing workbox file is not a 404"
# Compressed answers say they vary by what the browser accepts, so no cache in between mixes them up.
gz=$(curl -s -o /dev/null -D - -H 'Accept-Encoding: gzip' "$BASE$script" | tr -d '\r' | tr 'A-Z' 'a-z')
has_line "$gz" "^content-encoding: gzip" || fail "$script is not compressed"
has_line "$gz" "^vary: accept-encoding" || fail "a compressed answer lacks 'vary: accept-encoding'"

# The service worker and the workbox file it loads are real scripts, never the app's page (an address that is not a
# file falls back to it): without them an installed app never gets a new version.
is_script() { # path: 200, JavaScript, not HTML
  [ "$(status_of "$1")" = 200 ] || fail "$1 is not 200"
  has_line "$(head_of "$1")" "^content-type: (application|text)/javascript" || fail "$1 is not JavaScript"
  if has_line "$(curl -s "$BASE$1")" "<!(doctype|DOCTYPE) html"; then fail "$1 is the app's page, not a script"; fi
}
is_script /sw.js
expect_header /sw.js "cache-control: no-cache"
sw=$(curl -s "$BASE/sw.js")
workbox=$(printf '%s' "$sw" | grep -o 'workbox-[A-Za-z0-9_-]*' | head -1 || true) # named without .js
[ -n "$workbox" ] || fail "sw.js names no workbox file"
is_script "/$workbox.js"

[ "$(status_of /manifest.webmanifest)" = 200 ] || fail "/manifest.webmanifest is not 200"
expect_header /manifest.webmanifest "cache-control: no-cache"
expect_header /manifest.webmanifest "content-type: application/manifest+json"

for path in / /profile/data "$script" /sw.js /assets/missing-0000.js; do
  expect_header "$path" "x-content-type-options: nosniff"
  expect_header "$path" "referrer-policy: same-origin"
  expect_header "$path" "x-frame-options: deny"
  expect_header "$path" "content-security-policy: frame-ancestors 'none'"
done
if has_line "$(head_of /)" "^server: nginx/"; then fail "the server names its version"; fi

# The API address reached the bundle; nothing secret did.
docker exec "$NAME" grep -rqF "$API" /usr/share/nginx/html/assets || fail "the app does not call $API"
for secret in supabase_service_role_key SUPABASE_SERVICE_ROLE_KEY sb_secret_ FINODE_DATABASE_URL postgresql+psycopg; do
  if docker exec "$NAME" grep -rqF "$secret" /usr/share/nginx/html; then fail "the image carries '$secret'"; fi
done

echo "web image: all checks passed ($API)"
