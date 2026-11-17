#!/bin/sh
# Runs on every container start (nginx image entrypoint). Writes config.js and the
# security-headers snippet from API_URL, so one image works on any domain.
set -eu

api_url="${API_URL:-}"
api_url="${api_url%/}"

case "$api_url" in
  "" | http://* | https://*) ;;
  *) echo "API_URL must start with http:// or https:// (got: $api_url)" >&2; exit 1 ;;
esac
# The value lands in JavaScript and an HTTP header: allow URL characters only.
case "$api_url" in
  *[!A-Za-z0-9.:/_~%-]*) echo "API_URL contains characters that are not allowed" >&2; exit 1 ;;
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

echo "similarityly: API_URL=${api_url:-<same origin>} connect-src=$connect_src"
