from __future__ import annotations

import json
import sys
from typing import Any, Dict, TextIO

from . import __version__, db
from .agent import ask as agent_ask
from .config import mission_active
from .lifecycle import CONTAINMENT_MARKER

PROTOCOL_VERSION = 1
MAX_REQUEST_CHARS = 16_384
MAX_PROMPT_CHARS = 8_000
MAX_REQUEST_ID_CHARS = 128
_ALLOWED_OPS = frozenset({"ping", "status", "ask", "proposals", "diagnostics"})


def _mode() -> str:
    if mission_active():
        return "active"
    if CONTAINMENT_MARKER.exists():
        return "armed_off"
    return "demo"


def _base_response(request_id: str | None) -> Dict[str, Any]:
    response: Dict[str, Any] = {"v": PROTOCOL_VERSION}
    if request_id is not None:
        response["request_id"] = request_id
    return response


def _error(request_id: str | None, code: str, message: str) -> Dict[str, Any]:
    response = _base_response(request_id)
    response.update({"ok": False, "error": {"code": code, "message": message}})
    return response


def _request_id(request: Dict[str, Any]) -> str | None:
    value = request.get("request_id")
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > MAX_REQUEST_ID_CHARS:
        raise ValueError("request_id must be a non-empty string of at most 128 characters")
    return value


def dispatch_request(request: Any) -> Dict[str, Any]:
    """Handle one authenticated-controller request.

    Authentication and transport intentionally remain SSH's job. This function opens no
    socket, performs no network operation, and exposes no lifecycle/destructive command.
    It is suitable for use as an OpenSSH forced command behind a dedicated controller key.
    """
    if not isinstance(request, dict):
        return _error(None, "bad_request", "request must be a JSON object")

    try:
        request_id = _request_id(request)
    except ValueError as exc:
        return _error(None, "bad_request", str(exc))

    if request.get("v") != PROTOCOL_VERSION:
        return _error(request_id, "bad_version", f"protocol version must be {PROTOCOL_VERSION}")

    op = request.get("op")
    if not isinstance(op, str) or op not in _ALLOWED_OPS:
        return _error(
            request_id,
            "operation_denied",
            "allowed operations are ping, status, ask, proposals, and diagnostics",
        )

    mode = _mode()
    response = _base_response(request_id)

    if op == "ping":
        response.update({"ok": True, "result": {"service": "macbrain-remote", "mode": mode}})
        return response

    if op == "status":
        response.update({
            "ok": True,
            "result": {
                "version": __version__,
                "mode": mode,
                "mission_active": mode == "active",
                "containment_armed": mode != "demo",
                "network_policy": "inbound-controller-only; Mac Brain initiates no network connection",
            },
        })
        return response

    if op == "proposals":
        response.update({"ok": True, "result": {"proposals": db.list_proposals("open")}})
        return response

    if op == "diagnostics":
        from .diagnostics import build_diagnostic_packet
        sample_limit = request.get("sample_limit", 60)
        if not isinstance(sample_limit, int) or isinstance(sample_limit, bool):
            return _error(request_id, "bad_request", "sample_limit must be an integer")
        deep = request.get("deep", False)
        if not isinstance(deep, bool):
            return _error(request_id, "bad_request", "deep must be boolean")
        try:
            packet = build_diagnostic_packet(
                sample_limit=min(max(sample_limit, 5), 720),
                deep=deep,
            )
        except Exception as exc:
            return _error(request_id, "diagnostic_error", f"diagnostics failed: {type(exc).__name__}")
        response.update({"ok": True, "result": {"diagnostics": packet, "mode": mode}})
        return response

    # ask is deliberately read-only. Demo mode already allows local read-only reasoning.
    # Once containment is armed, the existing lifecycle rule still applies: no AI prompt
    # execution while Mac Brain is OFF.
    if mode == "armed_off":
        return _error(
            request_id,
            "mission_off",
            "Mac Brain is contained but OFF. Remote control cannot start it; use the existing explicit local start path.",
        )

    prompt = request.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return _error(request_id, "bad_prompt", "prompt must be a non-empty string")
    if len(prompt) > MAX_PROMPT_CHARS:
        return _error(request_id, "prompt_too_large", f"prompt exceeds {MAX_PROMPT_CHARS} characters")

    try:
        answer = agent_ask(prompt.strip())
    except Exception as exc:
        # Do not serialize traceback/internal state to the remote client.
        return _error(request_id, "local_ai_error", f"local AI request failed: {type(exc).__name__}")

    response.update({"ok": True, "result": {"answer": answer, "mode": mode}})
    return response


def run_stdio(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """Read exactly one JSON request from stdin and write exactly one JSON response.

    A one-request-per-SSH-session shape keeps the transport simple, auditable, and easy
    to wrap from phones or agent bridges. stdout contains JSON only.
    """
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout

    raw = stdin.read(MAX_REQUEST_CHARS + 1)
    if len(raw) > MAX_REQUEST_CHARS:
        response = _error(None, "request_too_large", f"request exceeds {MAX_REQUEST_CHARS} characters")
        stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        stdout.flush()
        return 2

    try:
        request = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError):
        response = _error(None, "invalid_json", "stdin must contain one valid JSON request")
        stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        stdout.flush()
        return 2

    response = dispatch_request(request)
    stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
    stdout.flush()
    return 0 if response.get("ok") else 2
