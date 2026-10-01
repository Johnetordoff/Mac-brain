# Run Mac Brain

## Status

**The PR #5 branch is runnable now.** Run it on the target Intel Big Sur Mac only after the branch's GitHub Actions check is green.

The installer deliberately proves the repository, machine, local model, SSH listener, and background worker **before** it changes the network. Network containment is not applied until the user explicitly types `ARM MAC BRAIN`.

## Prerequisites

1. macOS Big Sur 11.7.x on Intel x86_64 (the primary tested target).
2. At least 4 GiB free disk space; 8 GiB or more is preferable during bootstrap.
3. AC power connected.
4. **CPython 3.14.x**. Python 3.14.8 is the recommended current stable build. The official python.org macOS installer supports macOS 10.15 and later, including Big Sur.
5. Apple Command Line Tools. Mac Brain needs Apple's `git`, `make`, `cc`, and `c++` to build the pinned llama.cpp runtime.
6. Ordinary Internet access during bootstrap so the installer can clone llama.cpp and download the Qwen model.

No Homebrew package, pip package, virtualenv package set, Node package, or other third-party Python dependency is required.

See [DEPENDENCIES.md](DEPENDENCIES.md) for the complete external dependency inventory.

## If Python 3.14 is not installed

Use the official Python 3.14.8 macOS installer from:

https://www.python.org/downloads/release/python-3148/

Then verify that the 3.14 interpreter is available:

```text
python3.14 --version
```

It should print `Python 3.14.x`.

Do not replace or modify macOS's system Python. Mac Brain simply needs to be launched with the separately installed 3.14 interpreter.

## If Apple Command Line Tools are not installed

Check:

```text
xcode-select -p
```

If that does not print a developer-tools path, ask macOS to install the Command Line Tools:

```text
xcode-select --install
```

That is an Apple bootstrap prerequisite, not a Mac Brain application dependency.

## Run the current PR branch from an existing Mac-brain checkout

Do this while ordinary outbound networking still works:

```text
git fetch origin
git switch feature/lan-git-appliance
git pull --ff-only origin feature/lan-git-appliance
python3.14 --version
python3.14 install.py
```

If the branch is already checked out, `git switch` is harmless; the important update operation is the fast-forward-only pull.

If Mac Brain containment is already armed and therefore outbound Git is intentionally blocked, **do not widen the firewall just to fetch this branch**. Either perform deliberate physical recovery first or send the update inward from the authorized controller. The no-egress boundary is intentional.

## What the installer does before containment

Before any network restriction, `install.py`:

1. verifies it is running under CPython 3.14.x;
2. asks macOS `sudo` for administrator authentication;
3. runs the Python-only repository policy;
4. runs all unit tests;
5. checks Intel/Big Sur/SIP, RAM, free disk, load, and AC power;
6. verifies Apple Command Line Tools;
7. clones the pinned `llama.cpp` tag if it is not already present;
8. builds CPU-only `llama-cli` locally;
9. downloads the Qwen2.5-1.5B-Instruct Q4_K_M GGUF if it is not already present;
10. verifies the model SHA-256;
11. runs a real local-model smoke test;
12. verifies SSH/Remote Login;
13. runs a non-destructive performance/storage baseline;
14. starts the background worker briefly and verifies that it records evidence;
15. opens the demonstration console while normal networking still exists.

A failure in these stages stops installation before containment is applied.

## Demonstration and takeover

Use the demonstration console normally. When satisfied, type exactly:

```text
TAKE OVER MAC BRAIN
```

The installer then identifies the one controller IPv4 address that will be allowed to initiate SSH.

To actually apply containment, type exactly:

```text
ARM MAC BRAIN
```

That is the point at which Mac Brain makes its IPv4 configuration static, disables IPv6 on the active service, removes the default route, and installs/verifies the PF containment rules and watchdog.

Arming containment still leaves the AI worker **OFF**.

To start the local autonomous mission for the current boot, type exactly:

```text
START MAC BRAIN
```

The installer then enters the Mac Brain console.

## Later use

After installation and containment, from the physical Mac or the authorized inbound SSH controller:

```text
macbrain status
macbrain doctor
macbrain console
macbrain ask "Why are you slow right now?"
```

To stop the autonomous worker without removing containment:

```text
macbrain stop
```

A reboot also leaves the autonomous worker OFF until `macbrain start` is explicitly authorized again.

## Physical network recovery

On the physical Mac, using the same Python 3.14 interpreter that installed Mac Brain:

```text
sudo python3.14 scripts/network_unlock.py
```

This removes the Mac Brain containment layer and restores the saved network/PF state as closely as possible.

## Expected large bootstrap work

The first installation can be visibly slow on this machine because it builds llama.cpp locally and downloads/verifies roughly a gigabyte-scale Qwen model. That work occurs before containment and is reused on later installs when the verified runtime/model are already present.
