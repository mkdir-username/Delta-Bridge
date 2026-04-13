#!/bin/bash
set -euo pipefail

echo "[WL-SIM] Выключение whitelist-режима..."

iptables -F
iptables -P INPUT ACCEPT
iptables -P OUTPUT ACCEPT
iptables -P FORWARD ACCEPT

# Restore DNS to DHCP defaults
IFACE=$(ip route | awk '/default/{print $5}')
resolvectl revert "$IFACE"

echo "[WL-SIM] Нормальный режим восстановлен."
