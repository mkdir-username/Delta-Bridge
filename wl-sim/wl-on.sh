#!/bin/bash
set -euo pipefail

WL_FILE="/opt/wl-sim/whitelist-ips.txt"
YA_DNS1="77.88.8.1"
YA_DNS2="77.88.8.8"

# Auto-detect gateway subnet for SSH lockout protection
GW=$(ip route | awk '/default/{print $3}')
HOST_NET="${GW%.*}.0/24"

# Auto-detect primary network interface
IFACE=$(ip route | awk '/default/{print $5}')

if [[ ! -f "$WL_FILE" ]]; then
  echo "[WL-SIM] ERROR: $WL_FILE not found. Run resolve-wl.sh first."
  exit 1
fi

echo "[WL-SIM] Включение whitelist-режима..."
echo "[WL-SIM] SSH protection: $HOST_NET"

# Flush (policy stays ACCEPT until rules are in place)
iptables -P INPUT ACCEPT
iptables -P OUTPUT ACCEPT
iptables -P FORWARD ACCEPT
iptables -F INPUT
iptables -F OUTPUT
iptables -F FORWARD

# Loopback
iptables -A INPUT -i lo -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT

# SSH from LAN (lockout protection)
iptables -A INPUT -s "$HOST_NET" -p tcp --dport 22 -j ACCEPT
iptables -A OUTPUT -d "$HOST_NET" -p tcp --sport 22 -j ACCEPT

# Established/related
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Yandex DNS only
for dns in "$YA_DNS1" "$YA_DNS2"; do
  iptables -A OUTPUT -p udp -d "$dns" --dport 53 -j ACCEPT
  iptables -A OUTPUT -p tcp -d "$dns" --dport 53 -j ACCEPT
done

# Whitelist CIDRs
while IFS= read -r line; do
  [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
  cidr=$(echo "$line" | awk '{print $1}')
  iptables -A OUTPUT -d "$cidr" -j ACCEPT
done < "$WL_FILE"

# Log drops
iptables -A OUTPUT -j LOG --log-prefix "[WL-DROP] " --log-level 4
iptables -A INPUT -j LOG --log-prefix "[WL-DROP-IN] " --log-level 4

# NOW set DROP policy (all ACCEPT rules are in place)
iptables -P INPUT DROP
iptables -P OUTPUT DROP
iptables -P FORWARD DROP

# Switch DNS to Yandex via systemd-resolved
resolvectl dns "$IFACE" "$YA_DNS1" "$YA_DNS2"
resolvectl domain "$IFACE" "~."

echo "[WL-SIM] Whitelist активен."
echo "[WL-SIM] Test: ping 8.8.8.8 should timeout, ping 77.88.8.1 should work"
