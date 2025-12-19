#!/usr/bin/env bash
set -euo pipefail

# Remove only the rules added by redirect_tcp.sh
# Note: This is heuristic (based on patterns). Review before use in production.

iptables -t nat -S OUTPUT | awk '
  /-A OUTPUT .* -m addrtype --dst-type LOCAL -j RETURN/ ||
  /-A OUTPUT .* -p tcp -d 127\.0\.0\.1 -j RETURN/ ||
  /-A OUTPUT .* -p tcp .* --dport [0-9]+ .* -j RETURN/ ||
  /-A OUTPUT .* -p tcp .* -j REDIRECT --to-ports [0-9]+/ {
    sub("-A","-D");
    system("iptables -t nat " $0);
  }
'

echo "Remaining nat OUTPUT rules:"
iptables -t nat -S OUTPUT || true


