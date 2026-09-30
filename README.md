# Speed Up Mac Brain

**Speed Up Mac Brain** turns one old Intel Mac into a self-contained local maintenance agent whose permanent first mission is:

> **SPEED UP MAC BRAIN.** Gather evidence explaining why this Mac feels slow, find genuinely reclaimable storage and unnecessary background load, and surface concrete cleanup/performance proposals. Never destroy data merely because deleting it might improve performance.

Primary target: **13-inch Retina MacBook Pro (mid-2014), Intel, macOS Big Sur 11.7.10, ~6 GB RAM**. The installer still detects the actual machine values instead of assuming the reported specs are exact.

## The three-command install

On the old Mac:

```bash
git clone https://github.com/Johnetordoff/Mac-brain.git
cd Mac-brain
python3 install.py
```

Those are the only shell commands expected for bootstrap. The installer handles the rest interactively.

The first interactive event is ordinary macOS `sudo` authentication. **Mac Brain never reads, echoes, stores, or gives the administrator password to Qwen.** macOS handles the password.

## The install is deliberately two-stage

The key safety/UX rule is that Mac Brain must **prove it can inspect the machine intelligently before it is allowed to become the autonomous appliance**.

### Stage 1 — demonstration, networking still normal

Before any network containment is applied, the installer must successfully complete:

1. repository unit tests;
2. Big Sur / Intel / SIP preflight;
3. pinned CPU-only llama.cpp build;
4. SHA-256 verification of the local model;
5. a real local Qwen inference smoke test;
6. a verified local SSH listener on port 22;
7. a non-destructive performance/storage baseline;
8. an initial bounded list of the largest user files and known cleanup-candidate areas;
9. a background LaunchAgent proof-of-life test;
10. shell / PF configuration validation.

If any prerequisite fails, ordinary networking is left intact.

The installer then opens a **demonstration console** while networking is still normal:

```text
=== MAC BRAIN DEMONSTRATION STAGE ===
Hey John. I'm Mac Brain. Networking is still normal right now.
I can inspect this Mac, reason locally, and show you what I think is making it slow,
but I am not yet running the autonomous mission and I cannot delete anything on my own.
Ask me something like: can you speed this up?

macbrain-demo>
```

At this stage you can ask normal questions such as:

```text
can you speed this up?
show me the biggest files
what looks redundant?
what is using CPU?
```

Mac Brain can use its local inspection tools, including exact duplicate-file hashing, but autonomous background reasoning is not yet enabled and no network restriction has been applied.

Only when you are satisfied do you explicitly type:

```text
TAKE OVER MAC BRAIN
```

That returns to the installer. It still does **not** start the autonomous mission until network containment succeeds.

### Stage 2 — contained autonomous appliance

The installer then identifies **one exact IPv4 address** for the controller computer. If installation is being run through SSH it uses that SSH peer. Otherwise it asks for the controller IPv4 address interactively and verifies that it is on Mac Brain's directly attached LAN.

It then asks:

```text
Type ARM MAC BRAIN to apply containment and start the autonomous mission:
```

Only after that exact confirmation does the installer apply and verify the low-level network boundary. After containment succeeds, `SPEED UP MAC BRAIN` becomes a persistent background mission automatically.

## What “one-way” networking means technically

TCP cannot literally be one-way: an inbound SSH connection requires the Mac to transmit reply packets. The enforceable rule is therefore:

> **Mac Brain may not initiate an IP connection. The only ordinary remote IP connection allowed is an SSH connection initiated by the one explicitly authorized controller computer, plus the reply packets belonging to that state.**

Mac Brain uses several layers rather than trusting a prompt instruction:

- the active network service is changed from DHCP to the **same current IPv4 address as a static address**, so post-takeover DHCP traffic is unnecessary;
- IPv6 is disabled on that network service;
- the IPv4 default route is removed, so there is no route to the Internet even if an application tries;
- root-owned macOS **PF** rules allow localhost and controller-initiated IPv4 SSH, then `quick`-block other IP traffic on the active interface;
- the Mac Brain PF anchor is placed ahead of Apple's general PF filter anchor;
- a root-owned LaunchDaemon watchdog continually reasserts PF, IPv6-off, and no-default-route state if macOS networking changes;
- the ordinary Mac Brain agent has no root shell, no network tool, and no ability to modify the root-owned containment files.

This is intentionally defense-in-depth. PF is an advanced macOS packet-filter mechanism, not a stable application API, so the project does not rely on PF as the only barrier.

## What happens after takeover

After containment verifies successfully, the background LaunchAgent starts and the mission is marked active. The installer opens the normal console:

```text
Hey John. I'm Mac Brain, your local AI unit. My mission is already active: speed up this computer.
I'll keep working in the background after this terminal closes.
```

Closing that terminal or ending SSH does **not** stop the background mission. Later:

```bash
macbrain console
```

reconnects to the same running agent.

While the console is open, reports appear roughly every two minutes. The two-minute report cadence does **not** force model inference every two minutes; doing that on this dual-core Mac would make Mac Brain itself a performance problem.

Default cadence:

- cheap performance sample: every 60 seconds;
- short progress report: about every 120 seconds;
- rotating deeper filesystem pass: every 30 minutes while idle and on AC;
- local Qwen reasoning cycle: every 15 minutes while idle and on AC, starting on the first eligible cycle after takeover;
- interactive local reasoning whenever you ask Mac Brain a question.

The worn battery is part of the evidence. Cheap monitoring continues on battery, but expensive scans and Qwen inference pause unless the Mac is on AC power.

## Why Qwen2.5-1.5B Instruct

The default is:

```text
Qwen/Qwen2.5-1.5B-Instruct-GGUF
qwen2.5-1.5b-instruct-q4_k_m.gguf
```

Mac Brain intentionally stays on **Qwen2.5-1.5B Instruct Q4_K_M** for the first Big Sur build rather than chasing the newest small model.

Reasons:

- the Q4_K_M model is about 1.1 GB, leaving useful memory headroom on a ~6 GB machine;
- Qwen2.5 is strong at instruction following and structured/JSON output, which fits the bounded tool-call loop;
- it is supported by the older pinned llama.cpp generation used by this project;
- a newer model such as Qwen3-1.7B would require a newer runtime generation and a somewhat larger model, increasing compatibility and performance risk on a 2014 Intel Big Sur target;
- most of Mac Brain's useful intelligence is deliberately deterministic Python/macOS inspection, so the LLM does not need to carry all of macOS administration knowledge in its weights.

Inference defaults are deliberately modest: 2 CPU threads, 2048-token context, CPU-only. The smaller context is intentional on a ~6 GB machine to leave more RAM headroom for macOS and filesystem work.

## Mac Brain is not allowed to guess that “non-system” means “garbage”

The computer may contain mostly redundant data, but **any file not required by macOS is not automatically safe to delete**. A unique photo, document, source tree, private key, database, or archive can be non-system and still matter.

Mac Brain therefore separates:

1. **large** — measured size only;
2. **rebuildable** — e.g. specific caches / build artifacts with known regeneration behavior;
3. **exactly redundant** — byte-for-byte duplicate files confirmed by SHA-256;
4. **probably stale** — evidence such as application no longer installed, long-unused generated data, or abandoned tooling;
5. **approved for cleanup** — a human decision.

The model can reason across those facts but cannot skip those distinctions.

## Initial process / persistence / malware-signal audit

Before Mac Brain starts optimizing storage, it performs a non-destructive startup audit so an unexplained background program is not mistaken for ordinary age-related slowness. It inventories:

- the running process table and third-party executable paths;
- code signatures for a bounded set of non-system executables;
- user and system-wide LaunchAgents / LaunchDaemons and their targets;
- TCP listeners that are exposed beyond loopback;
- the presence/version metadata of Apple's local XProtect and MRT components when available.

Mac Brain deliberately calls the output **suspicious/unverified review items**, not malware verdicts. Unsigned developer tools, local servers, launch agents, and old utilities can all be legitimate. Anything unusual becomes evidence to explain before cleanup begins. The audit is available later as `macbrain security-audit` and as the local `security_audit` agent tool.

## Initial storage intelligence

The first baseline immediately performs bounded, low-priority work to surface useful targets rather than wandering blindly:

- largest regular files in the user's home directory above a threshold;
- large known candidate areas such as `~/Library/Caches`, Xcode DerivedData, Homebrew/npm/pip caches, Trash, and installers/archives;
- large directories;
- current disk free space, swap, load, processes, Spotlight, and related evidence.

The agent also has these local tools on demand:

```text
largest_files
```

which performs a bounded low-priority file walk, and:

```text
duplicate_large_files
```

which groups large files by byte size first and hashes only same-size candidates. Exact SHA-256 equality proves identical content; Mac Brain still does not automatically choose which copy should be removed.

## No autonomous deletion

Mac Brain may inspect and reason on its own. It may create a cleanup proposal. It may **not** approve its own cleanup proposal.

Example:

```text
P0007  Old Xcode DerivedData tree
       evidence: known rebuildable build-data location, measured size,
                 no active dependency established
       expected benefit: reclaim storage
       risk: future Xcode builds will regenerate data
```

Review:

```bash
macbrain proposals
macbrain proposal P0007
```

Reversible quarantine requires your explicit command:

```bash
macbrain approve P0007 --quarantine
```

Permanent deletion requires an additional explicit flag:

```bash
macbrain approve P0007 --delete --confirm-delete
```

Diagnostic proposals such as “high CPU process” or “large directory” are structurally prevented from being approved as deletion actions.

## What Mac Brain can inspect

The agent can inspect, among other things:

- disk usage and large files/directories;
- exact duplicate candidates among large files;
- processes and memory/swap evidence;
- user and system LaunchAgents/LaunchDaemons;
- Spotlight and Time Machine status;
- arbitrary local filesystem paths readable by the process;
- known macOS cleanup candidate areas;
- historical observations stored in its local SQLite database.

It is instructed to distinguish **OBSERVED facts**, **HYPOTHESES**, and **PROPOSALS** and to try to disprove its own explanations for slowness.

## Full Disk Access and macOS TCC

Administrator/root Unix permissions and macOS privacy permissions are separate. The installer does **not** bypass TCC. Most performance/storage work functions without it, but protected data such as Mail/Safari/Photos may still return `Operation not permitted` until Full Disk Access is granted manually in Big Sur's System Preferences.

Mac Brain should report unreadable areas rather than claiming it inspected them.

## SIP and protected boundaries

SIP is expected to remain enabled. Cleanup code rejects mutation of core/protected locations including `/System`, `/bin`, `/sbin`, protected `/usr`, raw devices, SSH/firewall control files, the user's SSH credentials, and Mac Brain's own state/control paths.

The first project phase is **understand and speed up the existing Big Sur installation**. Replacing or radically changing the operating system is deliberately a later human decision after this machine has been characterized and cleaned.

## SSH use after takeover

From the single authorized controller computer:

```bash
ssh YOUR_MAC_USERNAME@MAC_BRAIN_LAN_IP
```

Then:

```bash
macbrain console
macbrain doctor
macbrain status
macbrain ask "Why are you slow right now?"
macbrain ask "Find the biggest plausible garbage on this machine, verify what it is, and propose only things you have evidence I can remove."
macbrain proposals
```

The evidence database is:

```text
~/.macbrain/macbrain.sqlite3
```

## Updating after isolation

`git pull` from Mac Brain intentionally stops working after takeover because Mac Brain cannot initiate a GitHub connection. Update it by pushing files **into** the Mac from the controller over SSH/SCP, or physically remove containment first.

## Physical recovery

At the physical Mac:

```bash
sudo /bin/bash ./scripts/network_unlock.sh
```

This stops the root network watchdog, restores the saved PF configuration, and restores the recorded DHCP/manual and IPv6 mode as closely as possible. Mac Brain itself has no inspection tool that invokes this script.

## Development checks

```bash
python3 -m unittest discover -s tests -v
bash -n scripts/network_lock.sh scripts/network_unlock.sh scripts/uninstall.sh
python3 -m py_compile install.py macbrain/*.py
```

The runtime agent uses the Python standard library only.
