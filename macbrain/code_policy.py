from __future__ import annotations

import ast
import re
import sys
from pathlib import PurePosixPath
from typing import Iterable

PYTHON_SERIES = (3, 14)
PYTHON_SERIES_TEXT = "3.14"

# Declarative formats are data, not alternate implementation languages.
DECLARATIVE_SUFFIXES = {".json", ".toml", ".yaml", ".yml", ".plist", ".xml"}
BROWSER_DIR_NAMES = {"browser", "web"}
_BROWSER_JS_SUFFIXES = {".js", ".mjs"}

# Runtime code may import the standard library and this project, nothing else.
_LOCAL_IMPORT_ROOTS = {"macbrain", "install", "scripts", "tools"}
_STDLIB = frozenset(getattr(sys, "stdlib_module_names", ()))

_FENCE_RE = re.compile(r"```([A-Za-z0-9_+.-]*)\n(.*?)```", re.DOTALL)
_DECLARATIVE_FENCE_LANGS = {"json", "toml", "yaml", "yml", "xml", "plist"}
_PYTHON_FENCE_LANGS = {"python", "py"}
_BROWSER_FENCE_LANGS = {"javascript", "js"}
_FORBIDDEN_SHELL_FENCE_LANGS = {
    "bash", "sh", "shell", "zsh", "fish", "powershell", "ps1", "cmd", "bat",
}


def require_supported_python() -> None:
    if sys.version_info[:2] != PYTHON_SERIES:
        found = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        raise RuntimeError(
            f"Mac Brain requires CPython {PYTHON_SERIES_TEXT}.x exactly; found {found}. "
            "Stop and update Python before running Mac Brain."
        )


def _import_roots(tree: ast.AST) -> Iterable[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".", 1)[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".", 1)[0]


def validate_python_source(source: str, *, filename: str = "<generated>") -> None:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        raise ValueError(f"invalid Python source: {exc}") from exc
    for root in _import_roots(tree):
        if root in _LOCAL_IMPORT_ROOTS or root in _STDLIB:
            continue
        raise ValueError(f"third-party Python import is forbidden: {root}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                    raise ValueError("subprocess shell=True is forbidden")


def _path_is_browser(path: PurePosixPath) -> bool:
    return any(part in BROWSER_DIR_NAMES for part in path.parts)


def validate_generated_file(path: str, content: str) -> None:
    """Validate a future Mac Brain write before bytes are allowed to hit disk.

    Executable source is Python. Browser-only JavaScript is the sole source-language
    exception. JSON/TOML/YAML/plist/XML are permitted only as declarative data.
    """
    p = PurePosixPath(path)
    suffix = p.suffix.lower()
    if suffix == ".py":
        validate_python_source(content, filename=str(p))
        return
    if suffix in _BROWSER_JS_SUFFIXES and _path_is_browser(p):
        return
    if suffix in DECLARATIVE_SUFFIXES:
        return
    raise ValueError(f"Mac Brain may not write executable source in this format: {p}")


def enforce_response_code_policy(text: str, *, browser_context: bool = False) -> str:
    """Reject model responses that contain executable code in a forbidden language."""
    for match in _FENCE_RE.finditer(text or ""):
        language = match.group(1).strip().lower()
        body = match.group(2)
        if language in _PYTHON_FENCE_LANGS:
            validate_python_source(body)
            continue
        if language in _DECLARATIVE_FENCE_LANGS or language in {"text", "plaintext", ""}:
            continue
        if language in _BROWSER_FENCE_LANGS and browser_context:
            continue
        if language in _FORBIDDEN_SHELL_FENCE_LANGS:
            raise ValueError("Mac Brain may not generate shell programs or shell-script code")
        raise ValueError(f"Mac Brain may not generate {language or 'unknown'} code")
    return text
