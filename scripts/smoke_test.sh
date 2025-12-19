#!/usr/bin/env bash
set -euo pipefail

# Basic smoke test runner for transparent proxy path
# Pre-reqs:
#  - DCS (SOCKS5) running on 127.0.0.1:1081 (no auth)
#  - socks5_ppp.py running and listening on 0.0.0.0:6767 (default)
#  - redirect rules applied (scripts/redirect_tcp.sh)
#
# Edit TARGET_IP and PORT as needed to match a captured subnet/port combo.

TARGET_IP=${TARGET_IP:-203.0.113.10}
TARGET_PORT=${TARGET_PORT:-80}

echo "Attempting to curl http://${TARGET_IP}:${TARGET_PORT} with no proxy env..."
echo "Expect to see logs in socks5_ppp.py indicating SO_ORIGINAL_DST -> ${TARGET_IP}:${TARGET_PORT}"
curl --noproxy '*' -v "http://${TARGET_IP}:${TARGET_PORT}/" || true

echo "Done. Check the PPP logs for tunnel establishment and data flow."


