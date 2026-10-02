# Speed Up Mac Brain

**Speed Up Mac Brain** turns one old Intel Mac into a contained local maintenance helper and a small passive inbound-only Git vault.

Primary target: **13-inch Retina MacBook Pro (mid-2014), Intel, macOS Big Sur 11.7.10, ~6 GB RAM**.

Two hardware assumptions are non-negotiable:

1. **Mac Brain is slow.** Its small local model is not a reliable place for complicated programming, coordination, Git logic, or storage strategy. Complicated work should be prepared elsewhere and handed inward as explicit deterministic operations.
2. **Mac Brain has little storage.** It is not a general archive. Git storage is bounded and fail-closed; large brain histories should be selectively checkpointed elsewhere.

## User-first adaptation

Mac Brain's long-term purpose is broader than machine-health reporting: when the autonomous worker is **ON**, it should make the computer progressively better for the actual user. That means finding recurring performance bottlenecks and their concrete process/file/service causes, learning which parts of the UX the user already likes, avoiding churn in those areas, and making safe reversible user-space improvements where it has authority.

The governing design contract is documented in [USER_FIRST_ADAPTATION.md](USER_FIRST_ADAPTATION.md). Mac Brain is an adaptive layer on top of macOS rather than a replacement for it; host-OS protections, containment, destructive-action approval rules, and other safety boundaries remain authoritative. The same user-first contract is intended to be portable to other operating systems through platform-specific adapters.

## Python-only engineering rule

See [PYTHON_POLICY.md](PYTHON_POLICY.md). The short version is:

- Mac Brain application/control/containment/tool/test source is Python.
- Required interpreter: **CPython 3.14.x**.
- Python code uses the **standard library only**. `pyproject.toml` declares `dependencies = []`.
- Shell scripts and shell wrappers are forbidden.
- `shell=True` and invoking a shell interpreter from Python are forbidden.
- Browser JavaScript is allowed only for an explicitly browser-based surface under `browser/` or `web/`.
- Declarative Markdown, JSON, TOML, YAML, plist and XML are allowed as data/configuration.
- C is allowed only as a Python C-extension for a measured documented bottleneck under `native/`; there is no such extension in this version.
- Mac Brain-generated executable code is subject to the same rule and is rejected at runtime when it uses a forbidden fenced language.
- CI runs `tools/repo_policy.py` and rejects tracked source or imports that violate the rule. CI `run` bodies themselves execute with GitHub Actions' Python shell rather than authored shell commands.

The existing local Qwen model is executed through a pinned native `llama.cpp` executable. That is the one existing third-party native model-runtime boundary; it is **not** being mislabeled as Python or as standard-library code. It is not an allowed pattern for adding application logic or dependencies. If the rule is later tightened to prohibit even the model backend from being non-Python, Qwen must be removed or its inference backend replaced with a compliant Python/C-extension implementation.

## Bootstrap

Before doing anything else, verify the interpreter is CPython 3.14.x. The installer itself refuses to continue under any other Python series **before sudo, model bootstrap, or network containment**.

From the old Mac:

```text
python3 --version
git clone https://github.com/Johnetordoff/Mac-brain.git
cd Mac-brain
python3 install.py
```

If `python3` is not 3.14.x, update Python first and rerun. Mac Brain intentionally does not carry compatibility code for old Python forward once the project baseline moves.

The first privileged event is ordinary macOS `sudo` authentication. Python never reads, echoes, stores, or passes the administrator password to the model.

## Install lifecycle

Installation remains deliberately staged.

### Stage 1 — prove local components while networking is normal

Before containment, the installer must complete:

1. Python-only repository policy check;
2. repository unit tests;
3. Big Sur / Intel / SIP preflight;
4. early RAM/disk/load/power viability check;
5. pinned CPU-only local inference runtime bootstrap;
6. SHA-256 verification of the local model;
7. local Qwen smoke test;
8. verified local SSH listener on port 22;
9. non-destructive performance/storage baseline;
10. background LaunchAgent proof-of-life;
11. Python syntax validation of the installer, package, containment scripts, and policy tooling.

No shell program is generated or executed by Mac Brain during this process.

The demonstration console runs while ordinary networking is still intact. Only an explicit `TAKE OVER MAC BRAIN` handoff reaches the containment stage.

### Stage 2 — containment

The installer identifies exactly one IPv4 controller computer. It then requires the explicit phrase:

```text
ARM MAC BRAIN
```

Containment is implemented by Python programs under `scripts/` using fixed macOS system interfaces such as `pfctl`, `networksetup`, `route`, and `launchctl` through `subprocess` argument arrays. No shell interpreter is involved.

The enforceable network rule is:

> **Mac Brain initiates no IP connection to the Internet and no IP connection to any other LAN machine. The one ordinary remote doorway is an SSH connection initiated by the single authorized controller IPv4 address, plus reply packets belonging to that connection.**

Defense in depth:

- the current IPv4 address becomes static so DHCP is unnecessary after takeover;
- IPv6 is disabled on the active service;
- the IPv4 default route is removed;
- root-owned PF rules allow loopback and controller-initiated SSH, then block other IP traffic;
- the Mac Brain PF anchor is evaluated ahead of Apple's generic filter anchor;
- a root-owned **Python** LaunchDaemon watchdog reasserts PF, no-default-route, and IPv6-off state;
- the ordinary Mac Brain agent has no generic network tool and cannot modify the root containment files.

Arming containment does not automatically start the autonomous worker. A reboot also leaves the worker OFF until the user explicitly starts it.

## Secure inbound remote prompts

See [REMOTE_CONTROL.md](REMOTE_CONTROL.md).

Mac Brain exposes a small machine-readable control surface through the **existing inbound SSH path**. It does not add an HTTP listener, cloud poller, reverse tunnel, or outbound callback. A dedicated OpenSSH key can be restricted with a forced `macbrain remote` command so an external phone/controller/agent bridge can submit JSON prompts without receiving an interactive shell.

The remote surface permits only `ping`, `status`, read-only `proposals`, and `ask`. It cannot arm containment, start/stop the mission, approve cleanup, delete/quarantine data, run a shell, or execute arbitrary commands. Demo mode accepts read-only remote prompts; after containment, prompts are rejected whenever Mac Brain is OFF.

For agent integrations, `controller/macbrain_remote.py` provides a synchronous SSH client and `skills/macbrain-remote/SKILL.md` defines the required request/wait-for-response loop. These are controller-side components; they do not add outbound networking to Mac Brain.

## Slow-machine operating model

Mac Brain should not try to be clever merely because an LLM is present.

Default work is bounded:

- cheap performance sample: every 60 seconds;
- short report: about every 120 seconds;
- deeper filesystem pass: about every 30 minutes only while idle/on AC;
- local reasoning cycle: about every 15 minutes only while idle/on AC;
- only one local inference process at a time.

The worn battery and low storage are operating constraints, not incidental details. Expensive background work pauses on battery.

## Passive inbound-only Git vault

See [GIT_APPLIANCE.md](GIT_APPLIANCE.md).

Mac Brain can hold a **small selected set** of bare repositories under:

```text
~/.macbrain/git/
```

The Git path is intentionally mechanical and does not call the local model.

Commands:

```text
macbrain git capacity
macbrain git create brain-clone0
macbrain git list
macbrain git info brain-clone0
```

Important properties:

- Mac Brain never fetches, pulls, discovers, or synchronizes another repository.
- Another machine prepares the brain/repository and pushes it inward through the already-authorized SSH connection.
- `git list` is name-only; it does not crawl histories or recursively size repositories.
- automatic Git GC is disabled so the old Mac does not unexpectedly begin a heavy repack.
- one incoming receive is capped at 256 MiB.
- Git writes stop when free space reaches the larger of 1 GiB or 10% of the filesystem.
- the Git `pre-receive` disk guard is generated as Python, not shell.
- failed safety-guard setup deletes the new empty receiving repo instead of leaving an unsafe half-configured endpoint.
- no automatic deletion occurs to make room.

From the authorized controller, a repository can be used as an ordinary SSH Git remote:

```text
git remote add macbrain USER@MAC_BRAIN_LAN_IP:.macbrain/git/brain-clone0.git
git push macbrain --all
git push macbrain --tags
```

Those connections are initiated by the controller. Mac Brain does not initiate a connection back to the controller or elsewhere.

Compressed/encrypted `.brain` files often delta poorly. Mac Brain therefore should hold selected checkpoints, not every generation of large brain capsules.

## Local model scope

The local model is deliberately small. It may inspect deterministic evidence and create non-destructive proposals, but it is not trusted to administer the network, run a shell, or approve destructive actions.

Its system prompt explicitly says that generated executable code must be Python 3.14 standard-library-only. A second Python runtime guard checks fenced code before returning it. Future filesystem-write tools must call `macbrain.code_policy.validate_generated_file()` before writing source.

Mac Brain has no generic shell tool and no generic network tool.

## Storage and cleanup safety

Mac Brain distinguishes:

1. **large** — measured size only;
2. **rebuildable** — known generated/cache data;
3. **exactly redundant** — content verified by SHA-256;
4. **probably stale** — evidence-based hypothesis;
5. **approved for cleanup** — explicit human decision.

Large or old never means automatically disposable.

Cleanup proposals can be reviewed with:

```text
macbrain proposals
macbrain proposal P0007
```

Quarantine requires an explicit command:

```text
macbrain approve P0007 --quarantine
```

Permanent deletion additionally requires `--delete --confirm-delete`.

## Physical recovery

At the physical Mac, deliberate network recovery is Python-only:

```text
sudo python3 scripts/network_unlock.py
```

That stops the root Python watchdog and restores the recorded PF/network state as closely as possible. The ordinary Mac Brain agent has no tool that invokes recovery.

## Development checks

Use CPython 3.14.x:

```text
python3 tools/repo_policy.py
python3 -m unittest discover -s tests -v
python3 -m compileall -q install.py macbrain scripts tools tests
```

CI runs these checks on Python 3.14. A source-language, dependency, or interpreter-policy violation is a build failure.
