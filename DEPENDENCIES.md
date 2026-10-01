# Mac Brain dependency inventory

This file is the authoritative list of dependencies outside Mac Brain's own Python source.

## Python packages

**None.**

Mac Brain declares `dependencies = []` and has no optional Python dependencies. Runtime Python imports are limited to the CPython standard library and Mac Brain's own modules. There is no `pip install`, requirements file, Poetry/Pipenv/uv lock file, Homebrew Python package, or PyPI dependency.

## Required interpreter

- **CPython 3.14.x**. The currently recommended build for this project is **Python 3.14.8**.
- The official python.org macOS 3.14.8 installer supports macOS 10.15 and later, including the target macOS Big Sur 11.7.10 Intel machine.

Mac Brain does not attempt to make old system Python compatible. Invoke installation with the 3.14 interpreter, for example `python3.14 install.py`.

## Explicitly allowed native model dependency

- **llama.cpp**, pinned by the installer to tag `b4528`.
- It is cloned from `ggml-org/llama.cpp` before containment and built locally as CPU-only `llama-cli`.
- Its upstream C/C++ source is an accepted third-party inference dependency. Do **not** mechanically rewrite upstream C++ into C merely to satisfy the Python-only application-source rule.
- If profiling demonstrates a narrow Python/native integration bottleneck, a small Python C extension or C shim may be added under the documented bottleneck exception. No such extension should be created without a measured reason.

This exception is specific to the model runtime. It is not permission to add arbitrary native application dependencies.

## Model data dependency

- **Qwen2.5-1.5B-Instruct Q4_K_M GGUF**.
- The installer downloads the model from the Qwen Hugging Face repository before containment.
- The file is verified against the SHA-256 embedded in `install.py` before use.
- This is model data, not a Python package or source-code dependency.

## Apple Command Line Tools

Required to build the pinned llama.cpp runtime and to support Git operations:

- `/usr/bin/git`
- `/usr/bin/make`
- `/usr/bin/cc` (Apple clang)
- `/usr/bin/c++` (Apple clang++)
- `/usr/bin/xcode-select`

The installer verifies these before the build. No Homebrew compiler/toolchain is required.

## macOS system interfaces and utilities

Mac Brain intentionally uses fixed operating-system executables through Python `subprocess` argument arrays. These are part of macOS / Apple system tooling rather than separately installed Python dependencies.

Installation, containment, lifecycle, and diagnostics use:

- `sudo`
- `csrutil`
- `networksetup`
- `route`
- `ipconfig`
- `sysctl`
- `pmset`
- `system_profiler`
- `launchctl` / launchd
- `systemsetup`
- `pfctl` / PF
- `ps`
- `du`
- `file`
- `codesign`
- `lsof`
- `vm_stat`
- `mdutil`
- `tmutil`
- the macOS SSH/Remote Login service
- basic filesystem utilities used during privileged installation (`mkdir`, `cp`, `chown`, `chmod`)

Mac Brain does not invoke a shell interpreter and does not use `shell=True`.

## Network access required only before containment

The installer needs ordinary outbound networking before the user arms containment for:

1. the Mac Brain repository itself;
2. cloning the pinned `llama.cpp` source from GitHub;
3. downloading the Qwen GGUF model from Hugging Face.

After containment is armed, Mac Brain is intentionally unable to initiate network connections.

## CI-only dependencies

GitHub Actions uses:

- `actions/checkout@v4`
- `actions/setup-python@v6`
- a GitHub-hosted macOS runner

These are CI infrastructure and are not installed on Mac Brain.

## Things Mac Brain does not depend on

Mac Brain has no runtime dependency on Homebrew, pip, PyPI, requests, NumPy, pandas, PyTorch, TensorFlow, Playwright, Node.js, npm, Ruby gems, Docker, a cloud inference API, or a separately installed database server.

Python's `sqlite3` module is used through the standard library; it does not add a Python package dependency.
