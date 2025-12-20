#!/usr/bin/env bash
set -euo pipefail

LISTEN_PORT=${LISTEN_PORT:-6767}
DCS_PORT=${DCS_PORT:-1081}

# Mark used by DCS to bypass NAT redirection (see src/socks5_dcs.py SOCKS_PROXY_BYPASS_MARK)
BYPASS_MARK=${BYPASS_MARK:-1}
CHAIN=${CHAIN:-PPP_PROXY}

ROUTES=(
  "104.154.249.83 8891"
  "172.23.16.1 7978"
)

# Create / reset our dedicated chain
iptables -t nat -N "$CHAIN" 2>/dev/null || true
iptables -t nat -F "$CHAIN"

# Always bypass already-marked packets (DCS marks its outbound sockets)
iptables -t nat -A "$CHAIN" -m mark --mark "$BYPASS_MARK" -j RETURN

# Safety exclusions: don't capture local loopback or our own PPP/DCS listener ports
iptables -t nat -A "$CHAIN" -d 127.0.0.1/32 -p tcp -j RETURN
iptables -t nat -A "$CHAIN" -p tcp --dport "${DCS_PORT}" -j RETURN
iptables -t nat -A "$CHAIN" -p tcp --dport "${LISTEN_PORT}" -j RETURN

# Redirect selected targets through PPP
for entry in "${ROUTES[@]}"; do
  [[ -z "${entry// }" ]] && continue
  read -r DST_IP DST_PORT <<< "${entry}"
  iptables -t nat -A "$CHAIN" -p tcp -d "$DST_IP" --dport "$DST_PORT" -j REDIRECT --to-ports "${LISTEN_PORT}"
done

# If nothing matched, fall back to normal routing
iptables -t nat -A "$CHAIN" -j RETURN

# Ensure jump from OUTPUT exists near the top (no duplicates)
iptables -t nat -C OUTPUT -j "$CHAIN" 2>/dev/null || iptables -t nat -I OUTPUT 1 -j "$CHAIN"

echo "Applied nat OUTPUT -> $CHAIN (BYPASS_MARK=$BYPASS_MARK)"
iptables -t nat -S OUTPUT | sed -n '1,120p' || true
iptables -t nat -S "$CHAIN" || true