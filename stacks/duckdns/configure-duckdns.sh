#!/usr/bin/env bash

set -euo pipefail

STACK_DIR="/volume1/docker/duckdns"
CONFIG_FILE="${STACK_DIR}/duckdns.env"
UPDATER="${STACK_DIR}/update-duckdns.sh"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: Run this configuration helper as root." >&2
  exit 1
fi

if [[ ! -x "$UPDATER" ]]; then
  echo "ERROR: Install the DuckDNS updater first." >&2
  exit 1
fi

printf 'Subdominio DuckDNS (sin .duckdns.org): '
IFS= read -r -s domains
printf '\nToken DuckDNS: '
IFS= read -r -s token
printf '\n'

IFS=',' read -r -a domain_list <<< "$domains"
if [[ "${#domain_list[@]}" -eq 0 ]]; then
  echo "ERROR: A DuckDNS domain is required." >&2
  exit 1
fi
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

umask 077
temporary="$(mktemp "${CONFIG_FILE}.tmp.XXXXXX")"
trap 'rm -f "$temporary"' EXIT
printf 'DUCKDNS_DOMAINS=%s\nDUCKDNS_TOKEN=%s\n' "$domains" "$token" > "$temporary"

if ! DUCKDNS_CONFIG_FILE="$temporary" "$UPDATER"; then
  echo "ERROR: DuckDNS did not accept the configuration; the previous setup was preserved." >&2
  exit 1
fi

install -o root -g root -m 0600 "$temporary" "$CONFIG_FILE"
systemctl daemon-reload
systemctl enable --now duckdns-update.timer
systemctl start duckdns-update.service

echo "DuckDNS is configured and will refresh every five minutes."
