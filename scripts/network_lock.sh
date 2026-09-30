#!/bin/bash
set -euo pipefail

usage() {
  echo "Usage: sudo $0 --source A.B.C.D --interface en0 --gateway A.B.C.D --service 'Wi-Fi' --ip A.B.C.D --netmask A.B.C.D"
  exit 2
}

SOURCE=""
IFACE=""
GATEWAY=""
SERVICE=""
LOCAL_IP=""
NETMASK=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --source) SOURCE="${2:-}"; shift 2 ;;
    --interface) IFACE="${2:-}"; shift 2 ;;
    --gateway) GATEWAY="${2:-}"; shift 2 ;;
    --service) SERVICE="${2:-}"; shift 2 ;;
    --ip) LOCAL_IP="${2:-}"; shift 2 ;;
    --netmask) NETMASK="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done

[ "$(id -u)" -eq 0 ] || { echo "Must run as root." >&2; exit 1; }
for value in "$SOURCE" "$GATEWAY" "$LOCAL_IP" "$NETMASK"; do
  echo "$value" | /usr/bin/grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' || usage
done
echo "$IFACE" | /usr/bin/grep -Eq '^[A-Za-z0-9._-]+$' || usage
[ -n "$SERVICE" ] || usage

ANCHOR="/etc/pf.anchors/macbrain"
ANCHOR_NEW="/etc/pf.anchors/macbrain.new"
BACKUP="/etc/pf.conf.macbrain-backup"
PF_NEW="/etc/pf.conf.macbrain-new"
SUPPORT="/Library/Application Support/MacBrain"
DAEMON="/Library/LaunchDaemons/com.macbrain.networklock.plist"
WATCHDOG="$SUPPORT/network-watchdog.sh"
PF_STATE="$SUPPORT/pf-was-enabled"
NETWORK_BEFORE="$SUPPORT/network-before.txt"
NETWORK_META="$SUPPORT/network-meta"

/bin/mkdir -p "$SUPPORT"
/bin/chown root:wheel "$SUPPORT"
/bin/chmod 700 "$SUPPORT"

if [ ! -f "$PF_STATE" ]; then
  if /sbin/pfctl -s info 2>/dev/null | /usr/bin/grep -q 'Status: Enabled'; then
    echo enabled > "$PF_STATE"
  else
    echo disabled > "$PF_STATE"
  fi
  /bin/chown root:wheel "$PF_STATE"
  /bin/chmod 600 "$PF_STATE"
fi

if [ ! -f "$BACKUP" ]; then
  /bin/cp /etc/pf.conf "$BACKUP"
fi
if [ ! -f "$NETWORK_BEFORE" ]; then
  /usr/sbin/networksetup -getinfo "$SERVICE" > "$NETWORK_BEFORE"
fi
cat > "$NETWORK_META" <<META
SERVICE=$SERVICE
IFACE=$IFACE
GATEWAY=$GATEWAY
LOCAL_IP=$LOCAL_IP
NETMASK=$NETMASK
SOURCE=$SOURCE
META
/bin/chown root:wheel "$NETWORK_BEFORE" "$NETWORK_META"
/bin/chmod 600 "$NETWORK_BEFORE" "$NETWORK_META"

cat > "$ANCHOR_NEW" <<RULES
# Speed Up Mac Brain containment anchor. Root-owned; Mac Brain cannot modify it.
pass quick on lo0 all

# The ONE ordinary remote doorway: controller-initiated IPv4 SSH.
pass in quick on $IFACE inet proto tcp from $SOURCE to $LOCAL_IP port 22 flags S/SA keep state

# No other IP traffic. Established SSH replies are allowed by the state created above.
block drop quick on $IFACE inet6 all
block drop quick on $IFACE inet all
RULES
/bin/chown root:wheel "$ANCHOR_NEW"
/bin/chmod 600 "$ANCHOR_NEW"

# Build a prospective pf.conf with the Mac Brain filter anchor evaluated BEFORE
# Apple's generic filter anchor. 'quick' rules inside Mac Brain then terminate matching
# evaluation before later system pass rules can reopen egress.
/usr/bin/awk '
  /^[[:space:]]*anchor "macbrain"/ { next }
  /^[[:space:]]*load anchor "macbrain"/ { next }
  !inserted && /^[[:space:]]*anchor "com\.apple\/\*"/ {
    print "anchor \"macbrain\""
    inserted=1
  }
  { print }
  END {
    if (!inserted) print "anchor \"macbrain\""
    print "load anchor \"macbrain\" from \"/etc/pf.anchors/macbrain\""
  }
' /etc/pf.conf > "$PF_NEW"

OLD_ANCHOR=""
if [ -f "$ANCHOR" ]; then
  OLD_ANCHOR="/etc/pf.anchors/macbrain.previous"
  /bin/cp "$ANCHOR" "$OLD_ANCHOR"
fi
/bin/cp "$ANCHOR_NEW" "$ANCHOR"
if ! /sbin/pfctl -nf "$PF_NEW"; then
  if [ -n "$OLD_ANCHOR" ] && [ -f "$OLD_ANCHOR" ]; then
    /bin/mv "$OLD_ANCHOR" "$ANCHOR"
  else
    /bin/rm -f "$ANCHOR"
  fi
  /bin/rm -f "$ANCHOR_NEW" "$PF_NEW"
  echo "PF validation failed. Existing networking was left active." >&2
  exit 1
fi
/bin/rm -f "$OLD_ANCHOR" "$ANCHOR_NEW"
/bin/mv "$PF_NEW" /etc/pf.conf
/bin/chown root:wheel "$ANCHOR" /etc/pf.conf
/bin/chmod 600 "$ANCHOR"

rollback_all() {
  /bin/launchctl unload "$DAEMON" >/dev/null 2>&1 || true
  /bin/rm -f "$DAEMON" "$WATCHDOG"
  if [ -f "$BACKUP" ]; then
    /bin/cp "$BACKUP" /etc/pf.conf
    /sbin/pfctl -f /etc/pf.conf >/dev/null 2>&1 || true
  fi
  if [ -f "$PF_STATE" ] && /usr/bin/grep -q '^disabled$' "$PF_STATE"; then
    /sbin/pfctl -d >/dev/null 2>&1 || true
  fi
  /bin/rm -f "$ANCHOR"
  if [ -f "$NETWORK_BEFORE" ]; then
    if /usr/bin/head -1 "$NETWORK_BEFORE" | /usr/bin/grep -qi 'DHCP'; then
      /usr/sbin/networksetup -setdhcp "$SERVICE" >/dev/null 2>&1 || true
    else
      /usr/sbin/networksetup -setmanual "$SERVICE" "$LOCAL_IP" "$NETMASK" "$GATEWAY" >/dev/null 2>&1 || true
    fi
    if /usr/bin/grep -q '^IPv6: Automatic' "$NETWORK_BEFORE"; then
      /usr/sbin/networksetup -setv6automatic "$SERVICE" >/dev/null 2>&1 || true
    fi
  fi
}
trap 'echo "Containment setup failed; restoring pre-Mac-Brain networking." >&2; rollback_all' ERR

# Freeze the current IPv4 address as static so DHCP is not an allowed protocol after takeover.
# This deliberately uses the current address/subnet/router values gathered before arming.
/usr/sbin/networksetup -setmanual "$SERVICE" "$LOCAL_IP" "$NETMASK" "$GATEWAY"
# Disable IPv6 at the network-service layer, then remove the IPv4 Internet route.
/usr/sbin/networksetup -setv6off "$SERVICE"
/sbin/route -n delete default >/dev/null 2>&1 || true

# Apply PF containment.
/sbin/pfctl -f /etc/pf.conf
/sbin/pfctl -e >/dev/null 2>&1 || true

# Root-owned watchdog: defense in depth if macOS or a system service reloads PF or
# recreates the default route. This does not grant Mac Brain root; the agent cannot edit it.
cat > "$WATCHDOG" <<WATCH
#!/bin/bash
set -u
SERVICE=$(printf '%q' "$SERVICE")
while true; do
  if ! /sbin/pfctl -s info 2>/dev/null | /usr/bin/grep -q 'Status: Enabled' || \
     ! /sbin/pfctl -a macbrain -sr 2>/dev/null | /usr/bin/grep -q 'block drop quick'; then
    /sbin/pfctl -f /etc/pf.conf >/dev/null 2>&1 || true
    /sbin/pfctl -e >/dev/null 2>&1 || true
  fi
  /sbin/route -n get default >/dev/null 2>&1 && /sbin/route -n delete default >/dev/null 2>&1 || true
  /usr/sbin/networksetup -getinfo "$SERVICE" 2>/dev/null | /usr/bin/grep -q '^IPv6: Off' || \
    /usr/sbin/networksetup -setv6off "$SERVICE" >/dev/null 2>&1 || true
  /bin/sleep 2
done
WATCH
/bin/chown root:wheel "$WATCHDOG"
/bin/chmod 700 "$WATCHDOG"

cat > "$DAEMON" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.macbrain.networklock</string>
<key>ProgramArguments</key><array><string>$WATCHDOG</string></array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>ProcessType</key><string>Background</string>
</dict></plist>
PLIST
/bin/chown root:wheel "$DAEMON"
/bin/chmod 600 "$DAEMON"
/bin/launchctl unload "$DAEMON" >/dev/null 2>&1 || true
/bin/launchctl load "$DAEMON"

# Verify all layers. Any failure triggers rollback through ERR trap.
/sbin/pfctl -s info 2>/dev/null | /usr/bin/grep -q 'Status: Enabled'
/sbin/pfctl -a macbrain -sr 2>/dev/null | /usr/bin/grep -q "pass in quick on $IFACE inet proto tcp from $SOURCE"
/sbin/pfctl -a macbrain -sr 2>/dev/null | /usr/bin/grep -q 'block drop quick.*inet all\|block drop quick.*all'
! /sbin/route -n get default >/dev/null 2>&1
/usr/sbin/networksetup -getinfo "$SERVICE" | /usr/bin/grep -q '^IPv6: Off'

# Ensure Mac Brain's anchor is placed before the Apple wildcard filter anchor in pf.conf.
MB_LINE=$(/usr/bin/grep -n '^[[:space:]]*anchor "macbrain"' /etc/pf.conf | /usr/bin/head -1 | /usr/bin/cut -d: -f1)
APPLE_LINE=$(/usr/bin/grep -n '^[[:space:]]*anchor "com.apple/\*"' /etc/pf.conf | /usr/bin/head -1 | /usr/bin/cut -d: -f1 || true)
if [ -n "$APPLE_LINE" ] && [ "$MB_LINE" -ge "$APPLE_LINE" ]; then
  echo "Mac Brain PF anchor is not ahead of Apple's filter anchor." >&2
  false
fi

trap - ERR
echo "Mac Brain network containment armed and verified."
echo "Controller SSH source: $SOURCE"
echo "Interface: $IFACE ($SERVICE)"
echo "IPv4 default route: removed"
echo "IPv6: disabled on active service"
echo "PF: only controller-initiated SSH is permitted at the IP layer"
echo "Root watchdog: active"
