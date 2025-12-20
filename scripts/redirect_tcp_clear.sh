#!/usr/bin/env bash
set -euo pipefail

# iptables requires root; fail with a clear message instead of a confusing pipefail error.
if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "ERROR: must run as root. Try: sudo $0" >&2
  exit 1
fi

# Remove rules added by scripts/redirect_tcp_ppproxy.sh (deterministic via chain name).
CHAIN=${CHAIN:-PPP_PROXY}

if iptables -t nat -S OUTPUT 2>/dev/null | grep -q -- "-j ${CHAIN}"; then
  # Delete all jumps to CHAIN from OUTPUT (in case multiple got inserted)
  while iptables -t nat -D OUTPUT -j "$CHAIN" 2>/dev/null; do
    :
  done
fi

# Flush & delete the chain if present
iptables -t nat -F "$CHAIN" 2>/dev/null || true
iptables -t nat -X "$CHAIN" 2>/dev/null || true

# Also remove older direct OUTPUT rules from previous versions of redirect scripts (heuristic but narrowly scoped).
# We only touch rules that clearly relate to this project (ports 6767/1081, REDIRECT to 6767, owner RETURN).
iptables -t nat -S OUTPUT 2>/dev/null | awk '
  /-A OUTPUT .* -m owner --uid-owner [0-9]+ .* -j RETURN/ ||
  /-A OUTPUT .* -d 127\.0\.0\.1\/32 .* -j RETURN/ ||
  /-A OUTPUT .* -p tcp .* --dport (6767|1081) .* -j RETURN/ ||
  /-A OUTPUT .* -p tcp .* -j REDIRECT --to-ports 6767/ ||
  /-A OUTPUT .* -p tcp .* --dport [0-9]+ .* -j REDIRECT --to-ports 6767/ {
    sub("^-A","-D");
    system("iptables -t nat " $0);
  }
'

echo "Remaining nat OUTPUT rules:"
iptables -t nat -S OUTPUT || true


