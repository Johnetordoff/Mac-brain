#!/bin/bash
set -euo pipefail
LAUNCH="$HOME/Library/LaunchAgents/com.macbrain.performancehunter.plist"
/bin/launchctl unload "$LAUNCH" >/dev/null 2>&1 || true
/bin/rm -f "$LAUNCH"
echo "Mac Brain Performance Hunter stopped and its user LaunchAgent removed."
echo "Local model, evidence DB, configuration, and quarantine remain in ~/.macbrain."
echo "The SSH-only network lock is intentionally NOT removed by this script."
echo "A human administrator at the Mac must inspect /etc/pf.conf, /etc/pf.anchors/macbrain,"
echo "and /Library/LaunchDaemons/com.macbrain.networklock.plist, or run sudo scripts/network_unlock.sh"
echo "before deliberately reopening networking."
