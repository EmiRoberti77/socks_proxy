#!/usr/bin/env bash
set -euo pipefail

# Transparent redirect of selected outbound TCP flows into socks5_ppp.py
# Edit SUBNETS and PORTS to match your capture policy.

LISTEN_PORT=${LISTEN_PORT:-6767}
DCS_PORT=${DCS_PORT:-1081}

# Exact per-destination routes from src/socks5_ppp.py ROUTING_TABLE
# Format: "<DEST_IP> <DEST_PORT> <LOCAL_LISTEN_PORT>"
# 8887 -> 104.154.249.83:8891
# 6767 -> 172.23.16.1:7978
ROUTES=(
  "104.154.249.83 8891"
  "172.23.16.1 7978"
)

# Optional generic capture sets – leave empty unless you need broad matching
SUBNETS=(${SUBNETS:-})
PORTS=(${PORTS:-})

# Safety exclusions: don't capture local stack or our own proxy/DCS ports
iptables -t nat -C OUTPUT -p tcp -d 127.0.0.1 -j RETURN 2>/dev/null || \
iptables -t nat -A OUTPUT -p tcp -d 127.0.0.1 -j RETURN

iptables -t nat -C OUTPUT -p tcp --dport "${DCS_PORT}" -j RETURN 2>/dev/null || \
iptables -t nat -A OUTPUT -p tcp --dport "${DCS_PORT}" -j RETURN

iptables -t nat -C OUTPUT -p tcp --dport "${LISTEN_PORT}" -j RETURN 2>/dev/null || \
iptables -t nat -A OUTPUT -p tcp --dport "${LISTEN_PORT}" -j RETURN

# Before any REDIRECT rules
# PROXY_UID="${PROXY_UID:-proxy}"   # set to numeric uid or create user and use its uid
# iptables -t nat -C OUTPUT -m owner --uid-owner "$PROXY_UID" -j RETURN 2>/dev/null || \
# iptables -t nat -A OUTPUT -m owner --uid-owner "$PROXY_UID" -j RETURN

# Replace the for-loop body that reads 3 fields with 2 fields and uses LISTEN_PORT
for entry in "${ROUTES[@]}"; do
  [[ -z "${entry// }" ]] && continue
  read -r DST_IP DST_PORT <<< "${entry}"
  iptables -t nat -C OUTPUT -p tcp -d "$DST_IP" --dport "$DST_PORT" -j REDIRECT --to-ports "${LISTEN_PORT}" 2>/dev/null || \
  iptables -t nat -A OUTPUT -p tcp -d "$DST_IP" --dport "$DST_PORT" -j REDIRECT --to-ports "${LISTEN_PORT}"
done

for NET in "${SUBNETS[@]}"; do
  for P in "${PORTS[@]}"; do
    iptables -t nat -C OUTPUT -p tcp -d "$NET" --dport "$P" -j REDIRECT --to-ports "${LISTEN_PORT}" 2>/dev/null || \
    iptables -t nat -A OUTPUT -p tcp -d "$NET" --dport "$P" -j REDIRECT --to-ports "${LISTEN_PORT}"
  done
done

echo "Current matching nat OUTPUT rules:"
iptables-save | grep -E "OUTPUT.*(REDIRECT|RETURN).*" || true


