#!/bin/bash
set -euo pipefail

echo "[WL-SIM] Выключение whitelist-режима..."

iptables -F
iptables -P INPUT ACCEPT
iptables -P OUTPUT ACCEPT
iptables -P FORWARD ACCEPT

# Restore DNS to DHCP defaults
resolvectl revert enp0s1

echo "[WL-SIM] Нормальный режим восстановлен."
