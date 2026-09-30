#!/bin/bash
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo from the physical Mac." >&2; exit 1; }
BACKUP="/etc/pf.conf.macbrain-backup"
ANCHOR="/etc/pf.anchors/macbrain"
SUPPORT="/Library/Application Support/MacBrain"
DAEMON="/Library/LaunchDaemons/com.macbrain.networklock.plist"
WATCHDOG="$SUPPORT/network-watchdog.sh"
PF_STATE="$SUPPORT/pf-was-enabled"
NETWORK_BEFORE="$SUPPORT/network-before.txt"
NETWORK_META="$SUPPORT/network-meta"
CONTAINMENT_MARKER="$SUPPORT/containment-active"

[ -f "$BACKUP" ] || { echo "No pre-Mac-Brain pf backup found." >&2; exit 1; }
/bin/launchctl unload "$DAEMON" >/dev/null 2>&1 || true
/bin/rm -f "$DAEMON" "$WATCHDOG" "$CONTAINMENT_MARKER"

SERVICE=""
GATEWAY=""
LOCAL_IP=""
NETMASK=""
if [ -f "$NETWORK_META" ]; then
  # Values were validated and written by the root-only lock script. Parse only known keys.
  SERVICE=$(/usr/bin/awk -F= '$1=="SERVICE"{sub(/^SERVICE=/,"");print;exit}' "$NETWORK_META")
  GATEWAY=$(/usr/bin/awk -F= '$1=="GATEWAY"{print $2;exit}' "$NETWORK_META")
  LOCAL_IP=$(/usr/bin/awk -F= '$1=="LOCAL_IP"{print $2;exit}' "$NETWORK_META")
  NETMASK=$(/usr/bin/awk -F= '$1=="NETMASK"{print $2;exit}' "$NETWORK_META")
fi

/bin/cp "$BACKUP" /etc/pf.conf
/sbin/pfctl -f /etc/pf.conf
if [ -f "$PF_STATE" ] && /usr/bin/grep -q '^disabled$' "$PF_STATE"; then
  /sbin/pfctl -d >/dev/null 2>&1 || true
fi
/bin/rm -f "$ANCHOR"

if [ -n "$SERVICE" ] && [ -f "$NETWORK_BEFORE" ]; then
  if /usr/bin/head -1 "$NETWORK_BEFORE" | /usr/bin/grep -qi 'DHCP'; then
    /usr/sbin/networksetup -setdhcp "$SERVICE"
  elif [ -n "$LOCAL_IP" ] && [ -n "$NETMASK" ] && [ -n "$GATEWAY" ]; then
    /usr/sbin/networksetup -setmanual "$SERVICE" "$LOCAL_IP" "$NETMASK" "$GATEWAY"
  fi
  if /usr/bin/grep -q '^IPv6: Automatic' "$NETWORK_BEFORE"; then
    /usr/sbin/networksetup -setv6automatic "$SERVICE"
  fi
fi

echo "Mac Brain network containment removed by local administrator. Pre-install PF/network configuration restored as closely as recorded."
