#!/bin/sh
# Runs on every container start (nginx image entrypoint). Writes config.js, the
# security-headers snippet and the /api/ location from API_URL, so one image works
# on any domain.
#   API_URL       public API URL for a separate API domain; empty = same origin
#   API_UPSTREAM  where nginx proxies /api/ in same-origin mode (default http://api:8000)
set -eu

api_url="${API_URL:-}"
api_url="${api_url%/}"
api_upstream="${API_UPSTREAM:-http://api:8000}"
api_upstream="${api_upstream%/}"

case "$api_url" in
  "" | http://* | https://*) ;;
  *) echo "API_URL must start with http:// or https:// (got: $api_url)" >&2; exit 1 ;;
esac
# The value lands in JavaScript and an HTTP header: allow URL characters only.
case "$api_url" in
  *[!A-Za-z0-9.:/_~%-]*) echo "API_URL contains characters that are not allowed" >&2; exit 1 ;;
esac

case "$api_upstream" in
  http://* | https://*) ;;
  *) echo "API_UPSTREAM must start with http:// or https:// (got: $api_upstream)" >&2; exit 1 ;;
esac
case "$api_upstream" in
  *[!A-Za-z0-9.:/_~%-]*) echo "API_UPSTREAM contains characters that are not allowed" >&2; exit 1 ;;
esac

connect_src="'self'"
if [ -n "$api_url" ]; then
  # CSP connect-src takes an origin: scheme://host[:port], no path.
  origin=$(printf '%s' "$api_url" | sed -E 's#^(https?://[^/]+).*$#\1#')
  connect_src="'self' $origin"
fi

printf '// Generated at container start from API_URL.\nwindow.__SIM_CONFIG__ = { apiUrl: "%s" };\n' "$api_url" \
  > /usr/share/nginx/html/config.js

sed "s#__CONNECT_SRC__#$connect_src#" /etc/nginx/snippets/security-headers.conf.template \
  > /etc/nginx/snippets/security-headers.conf

api_location=/etc/nginx/snippets/api-location.conf
if [ -n "$api_url" ]; then
  # The UI calls API_URL directly; answer /api/ here with a plain 404 instead of
  # the SPA fallback, and never reference an upstream.
  cat > "$api_location" <<'CONF'
location /api/ {
    include /etc/nginx/snippets/security-headers.conf;
    return 404;
}
CONF
else
  cat > "$api_location" <<CONF
location /api/ {
    include /etc/nginx/snippets/security-headers.conf;
    proxy_pass $api_upstream;
    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_read_timeout 300s;
}
CONF
fi

if [ -n "$api_url" ]; then
  echo "similarityly: API_URL=$api_url (separate origin) connect-src=$connect_src"
else
  echo "similarityly: same-origin API, /api/ -> $api_upstream connect-src=$connect_src"
fi
