#!/usr/bin/env bash

set -euo pipefail

CONFIG_FILE="${DUCKDNS_CONFIG_FILE:-/volume1/docker/duckdns/duckdns.env}"
CURL_BIN="${DUCKDNS_CURL_BIN:-/usr/bin/curl}"

if [[ ! -r "$CONFIG_FILE" ]]; then
  echo "ERROR: DuckDNS configuration is missing or unreadable." >&2
  exit 1
fi

domains=""
token=""
while IFS='=' read -r key value || [[ -n "${key}${value}" ]]; do
  key="${key%$'\r'}"
  value="${value%$'\r'}"
  case "$key" in
    ""|'#'*) continue ;;
    DUCKDNS_DOMAINS)
      [[ -z "$domains" ]] || { echo "ERROR: Duplicate DuckDNS domains." >&2; exit 1; }
      domains="$value"
      ;;
    DUCKDNS_TOKEN)
      [[ -z "$token" ]] || { echo "ERROR: Duplicate DuckDNS token." >&2; exit 1; }
      token="$value"
      ;;
    *)
      echo "ERROR: Invalid DuckDNS configuration." >&2
      exit 1
      ;;
  esac
done < "$CONFIG_FILE"

if [[ -z "$domains" || -z "$token" ]]; then
  echo "ERROR: DuckDNS domains and token are required." >&2
  exit 1
fi

IFS=',' read -r -a domain_list <<< "$domains"
for domain in "${domain_list[@]}"; do
  if [[ ! "$domain" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]]; then
    echo "ERROR: Invalid DuckDNS domain." >&2
    exit 1
  fi
done

if [[ ! "$token" =~ ^[A-Za-z0-9-]{20,128}$ ]]; then
  echo "ERROR: Invalid DuckDNS token." >&2
  exit 1
fi

# Supplying the URL through curl's standard input keeps the token out of the
# process list. DuckDNS detects the public IPv4 address when ip is empty.
curl_config="$(printf 'url = "https://www.duckdns.org/update?domains=%s&token=%s&ip="\n' \
  "$domains" "$token")"
if ! response="$(
  "$CURL_BIN" \
    --silent \
    --fail \
    --retry 2 \
    --retry-delay 2 \
    --connect-timeout 10 \
    --max-time 30 \
    --config - <<< "$curl_config" 2>/dev/null
)"; then
  echo "ERROR: DuckDNS update request failed." >&2
  exit 1
fi

if [[ "$response" != "OK" ]]; then
  echo "ERROR: DuckDNS rejected the update." >&2
  exit 1
fi

echo "DuckDNS update OK."
