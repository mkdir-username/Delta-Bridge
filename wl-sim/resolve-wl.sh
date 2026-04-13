#!/bin/bash
set -euo pipefail

OUT="/opt/wl-sim/whitelist-ips.txt"
> "$OUT"

resolve_and_whois() {
  local domain="$1"
  local section="$2"

  if [[ "$domain" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    local cidr
    cidr=$(whois "$domain" 2>/dev/null | grep -i -m1 "route:" | awk '{print $2}' || true)
    if [[ -z "$cidr" ]]; then
      cidr="${domain}/32"
    fi
    echo "$cidr # $domain [$section]" >> "$OUT"
    return
  fi

  local ips
  ips=$(dig +short A "$domain" 2>/dev/null | grep -E '^[0-9]+\.' || true)

  if [[ -z "$ips" ]]; then
    echo "# WARN: no A records for $domain" >> "$OUT"
    return
  fi

  for ip in $ips; do
    local cidr
    cidr=$(whois "$ip" 2>/dev/null | grep -i -m1 "route:" | awk '{print $2}' || true)
    if [[ -z "$cidr" ]]; then
      cidr="$(echo "$ip" | cut -d. -f1-3).0/24"
    fi
    echo "$cidr # $domain -> $ip [$section]" >> "$OUT"
  done
}

echo "# WL-SIM whitelist IPs — generated $(date -I)" >> "$OUT"
echo "# Source: field test 2026-04-13 SPb mobile" >> "$OUT"
echo "" >> "$OUT"

echo "# === CONFIRMED ===" >> "$OUT"
for d in \
  77.88.8.1 77.88.8.8 \
  yandex.ru ya.ru mail.yandex.ru imap.yandex.ru smtp.yandex.ru \
  passport.yandex.ru translate.yandex.ru dns.yandex.net \
  alfabank.ktalk.ru matrix.ktalk.ru ktalk.ru alfabank.ru; do
  echo "  resolving $d ..." >&2
  resolve_and_whois "$d" "CONFIRMED"
done

echo "" >> "$OUT"
echo "# === PROBABLE ===" >> "$OUT"
for d in \
  vk.com ok.ru mail.ru imap.mail.ru sberbank.ru online.sberbank.ru \
  tinkoff.ru gosuslugi.ru nalog.gov.ru cbr.ru mos.ru rustore.ru \
  rutube.ru api.vk.com oauth.yandex.ru api.passport.yandex.ru \
  disk.yandex.ru music.yandex.ru kinopoisk.ru t.me api.telegram.org; do
  echo "  resolving $d ..." >&2
  resolve_and_whois "$d" "PROBABLE"
done

# Deduplicate
TMPF="$OUT.tmp"
sort -t'/' -k1,1 -u -o "$TMPF" "$OUT"
head -3 "$OUT" > "$OUT.dedup"
grep -v '^#' "$TMPF" | grep -v '^$' | sort -t. -k1,1n -k2,2n -k3,3n -k4,4n >> "$OUT.dedup" || true
mv "$OUT.dedup" "$OUT"
mv "$TMPF" /dev/null 2>/dev/null || true

echo ""
echo "Done. $(grep -cv '^#\|^$' "$OUT") unique CIDR entries in $OUT"
