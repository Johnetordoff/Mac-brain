#!/usr/bin/env python3
from __future__ import annotations

import ast
import os
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PYTHON = (3, 14)
REQUIRED_SPEC = ">=3.14,<3.15"
LOCAL_IMPORT_ROOTS = {"macbrain", "install"}
STDLIB = frozenset(sys.stdlib_module_names)

DECLARATIVE_OR_DOC_SUFFIXES = {".md", ".toml", ".yaml", ".yml", ".json", ".plist", ".xml"}
BROWSER_JS_SUFFIXES = {".js", ".mjs"}
BROWSER_DIR_NAMES = {"browser", "web"}
C_EXTENSION_SUFFIXES = {".c", ".h"}
FORBIDDEN_MANIFEST_NAMES = {
    "Pipfile", "Pipfile.lock", "poetry.lock", "uv.lock", "setup.py", "setup.cfg",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
}
SHELL_NAMES = {"sh", "bash", "zsh", "fish", "dash", "ksh", "powershell", "pwsh", "cmd.exe"}


def _tracked_files() -> list[PurePosixPath]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, stdout=subprocess.PIPE,
    )
    return [PurePosixPath(x.decode("utf-8")) for x in result.stdout.split(b"\0") if x]


def _is_browser_path(path: PurePosixPath) -> bool:
    return any(part in BROWSER_DIR_NAMES for part in path.parts)


def _allowed_file_kind(path: PurePosixPath, tracked: set[PurePosixPath]) -> str | None:
    if path.name in {"LICENSE", ".gitignore"}:
        return None
    if path.name in FORBIDDEN_MANIFEST_NAMES or path.name.startswith("requirements"):
        return "dependency/package-manager manifest is forbidden"
    if path.suffix == ".py":
        return None
    if path.name.endswith(".plist.template"):
        return None
    if path.suffix in DECLARATIVE_OR_DOC_SUFFIXES:
        return None
    if path.suffix in BROWSER_JS_SUFFIXES:
        if _is_browser_path(path):
            return None
        return "JavaScript is allowed only under a browser/ or web/ tree"
    if path.suffix in C_EXTENSION_SUFFIXES:
        declaration = PurePosixPath("native/BOTTLENECK.md")
        if path.parts and path.parts[0] == "native" and declaration in tracked:
            return None
        return "C is allowed only for a documented Python C-extension bottleneck under native/"
    return "tracked file type is not permitted by the Python-only repository policy"


def _import_roots(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".", 1)[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".", 1)[0]


def _constant_text(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _subprocess_program(call: ast.Call) -> tuple[str | None, list[str]]:
    if not call.args:
        return None, []
    arg = call.args[0]
    if not isinstance(arg, (ast.List, ast.Tuple)):
        return None, []
    values = [_constant_text(item) for item in arg.elts]
    if not values or values[0] is None:
        return None, [value for value in values if value is not None]
    return os.path.basename(values[0]), [value for value in values if value is not None]


def _check_python(path: PurePosixPath) -> list[str]:
    full = ROOT / path
    source = full.read_text(encoding="utf-8")
    errors: list[str] = []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"{path}: invalid Python syntax: {exc}"]
    for root in _import_roots(tree):
        if root in STDLIB or root in LOCAL_IMPORT_ROOTS:
            continue
        errors.append(f"{path}: third-party import forbidden: {root}")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                errors.append(f"{path}:{node.lineno}: shell=True is forbidden")
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            owner, attr = node.func.value.id, node.func.attr
            if owner == "os" and attr in {"system", "popen"}:
                errors.append(f"{path}:{node.lineno}: os.{attr} is forbidden")
            if owner == "subprocess" and attr in {"run", "Popen", "call", "check_call", "check_output"}:
                program, argv = _subprocess_program(node)
                if program and program in SHELL_NAMES:
                    errors.append(f"{path}:{node.lineno}: invoking a shell interpreter is forbidden")
                if program and program.startswith("pip"):
                    errors.append(f"{path}:{node.lineno}: installing Python packages is forbidden")
                if program and program.startswith("python") and "-m" in argv and "pip" in argv:
                    errors.append(f"{path}:{node.lineno}: installing Python packages is forbidden")
    if source.startswith("#!") and "python" not in source.splitlines()[0].lower():
        errors.append(f"{path}: executable shebang must be Python")
    return errors


def _check_pyproject() -> list[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data.get("project", {})
    errors: list[str] = []
    if project.get("requires-python") != REQUIRED_SPEC:
        errors.append(f"pyproject.toml: requires-python must be exactly {REQUIRED_SPEC}")
    if project.get("dependencies") not in (None, []):
        errors.append("pyproject.toml: runtime dependencies are forbidden")
    if project.get("optional-dependencies"):
        errors.append("pyproject.toml: optional third-party dependencies are forbidden")
    return errors


def main() -> int:
    errors: list[str] = []
    if sys.version_info[:2] != REQUIRED_PYTHON:
        errors.append(
            f"policy checker must run under CPython {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}.x; "
            f"found {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )
    tracked_list = _tracked_files()
    tracked = set(tracked_list)
    for path in tracked_list:
        error = _allowed_file_kind(path, tracked)
        if error:
            errors.append(f"{path}: {error}")
        if path.suffix == ".py":
            errors.extend(_check_python(path))
    errors.extend(_check_pyproject())
    if errors:
        print("Mac Brain Python-only policy FAILED:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("Mac Brain Python-only policy: OK")
    print("  executable source: Python only")
    print("  Python series: 3.14.x")
    print("  Python dependencies: standard library only")
    print("  browser JavaScript: allowed only under browser/ or web/")
    print("  C extension: allowed only under native/ with BOTTLENECK.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
