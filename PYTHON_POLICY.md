# Mac Brain Python-only engineering policy

This is a repository invariant, not a preference.

## Executable source

All Mac Brain executable source code is Python.

The only source-language exceptions are:

1. **Browser JavaScript** (`.js`/`.mjs`) when code is explicitly part of a browser surface, and only under a `browser/` or `web/` tree.
2. **A Python C extension** (`.c`/`.h`) when a measured performance bottleneck cannot reasonably be solved in Python. C extension source must live under `native/` and the bottleneck must be documented in `native/BOTTLENECK.md` before the C source is accepted.
3. Declarative data/configuration formats such as JSON, TOML, YAML, plist, XML, Markdown, and GitHub Actions YAML. These are not executable implementation languages.

Shell scripts, AppleScript, Ruby, Perl, TypeScript, standalone C/C++, and other implementation languages are not permitted.

Mac Brain may invoke fixed macOS system programs (for example `pfctl`, `networksetup`, `launchctl`, Git, and SSH) from Python with `subprocess`. It may not invoke a shell interpreter, use `shell=True`, or generate a shell program as an intermediate layer.

## Python baseline

Mac Brain currently requires **CPython 3.14.x**.

As of October 1, 2026, Python 3.14 is the current stable feature series published by Python.org; 3.15 is still a pre-release at the time this policy was written. The supported series is deliberately explicit: when the project chooses a new mainstream stable series, updating this baseline takes priority over feature work.

`pyproject.toml`, runtime checks, and CI must agree on the same Python series.

## Dependencies

Mac Brain Python code is **standard-library-only**.

No runtime or optional third-party Python dependencies are permitted. Do not add requirements files, package-manager lock files, `pip install` steps, or imports from PyPI packages.

The repository policy checker parses every tracked Python file and fails CI when a top-level import is not from the Python standard library or Mac Brain itself.

## Mac Brain-generated code

The local model is small and unreliable for complicated programming. Complicated work should be prepared elsewhere and handed to Mac Brain explicitly.

If Mac Brain is nevertheless asked to produce executable code:

- default and required language: Python 3.14;
- libraries: Python standard library only;
- no package-install instructions;
- no shell scripts or shell wrappers;
- browser JavaScript is allowed only when the task is explicitly browser code;
- declarative JSON/TOML/YAML/plist/XML may be produced as data/configuration;
- a C extension requires a documented measured bottleneck first.

The runtime response guard rejects fenced executable code in forbidden languages. Any future filesystem-write tool must call `macbrain.code_policy.validate_generated_file()` before writing source.

## Enforcement

Run:

```text
python3 tools/repo_policy.py
```

CI runs the same guard. It checks:

- CPython 3.14.x is the interpreter running the check;
- `pyproject.toml` requires `>=3.14,<3.15`;
- no third-party or optional Python dependencies are declared;
- every tracked executable source file uses an allowed language/location;
- every Python import is standard-library or local;
- `shell=True`, shell-interpreter subprocesses, and Python package installation are absent;
- C is absent unless the documented C-extension bottleneck exception is active.

A change that violates the guard does not belong in Mac Brain.
