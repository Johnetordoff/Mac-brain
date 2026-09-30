# Mac Brain lifecycle

Mac Brain is **OFF by default**. Network containment and AI activation are separate states.

## Start Mac Brain

Mac Brain can start only from an interactive terminal after verified network containment exists:

```bash
macbrain start
```

Then type the exact code word when prompted:

```text
START MAC BRAIN
```

Ordinary conversation, `macbrain ask`, a login, and a reboot cannot start the AI mission.

## Stop Mac Brain

```bash
macbrain stop
```

This immediately marks the mission inactive, unloads the Mac Brain LaunchAgent, and terminates Mac Brain's local Qwen process if one is running. There is no automatic restart. A reboot leaves Mac Brain OFF.

Inside the console, the exact code word:

```text
STOP MAC BRAIN
```

performs the same shutdown.

## Reboot behavior

The AI/background LaunchAgent has no `RunAtLoad`, `KeepAlive`, interval, or calendar trigger. The mission-active marker is bound to the current boot, so a marker from an earlier boot is invalid. After verified containment, the background worker also exits immediately if it is launched without a current authorized active marker.

The root-owned **network containment watchdog is separate** and may continue/restart to preserve the no-egress boundary. That watchdog is not the AI and does not run Qwen.

## Safety rule

`macbrain start` refuses to start unless the root-owned verified-containment marker exists. Removing containment with the local administrator recovery script also removes that marker, so Mac Brain cannot be started in autonomous mode outside the intended network boundary.
