#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict

DEFAULT_TIMEOUT_SECONDS = 300


def build_request(op: str, prompt: str | None = None, request_id: str | None = None) -> Dict[str, Any]:
    request: Dict[str, Any] = {
        "v": 1,
        "op": op,
        "request_id": request_id or str(uuid.uuid4()),
    }
    if op == "ask":
        if not prompt or not prompt.strip():
            raise ValueError("ask requires a non-empty prompt")
        request["prompt"] = prompt.strip()
    return request


def call_macbrain(
    *,
    host: str,
    user: str,
    identity_file: str,
    request: Dict[str, Any],
    port: int = 22,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Send one request over a dedicated forced-command SSH key and wait for one reply.

    This controller code is intended to run OUTSIDE Mac Brain. It never asks the SSH
    server for a shell or remote command. The server-side key should force
    /usr/local/bin/macbrain remote.
    """
    identity = str(Path(identity_file).expanduser())
    args = [
        "/usr/bin/ssh",
        "-T",
        "-p",
        str(port),
        "-i",
        identity,
        "-oBatchMode=yes",
        "-oIdentitiesOnly=yes",
        "-oStrictHostKeyChecking=yes",
        "-oClearAllForwardings=yes",
        "-oForwardAgent=no",
        "-oRequestTTY=no",
        f"{user}@{host}",
    ]
    payload = json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n"
    try:
        result = subprocess.run(
            args,
            input=payload,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Mac Brain did not reply within {timeout_seconds} seconds; "
            "do not assume the request completed."
        ) from exc

    if result.returncode not in (0, 2):
        detail = (result.stderr or "").strip()
        raise RuntimeError(
            f"SSH transport failed with exit code {result.returncode}"
            + (f": {detail}" if detail else "")
        )

    raw = (result.stdout or "").strip()
    if not raw:
        raise RuntimeError("Mac Brain returned no JSON response")
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Mac Brain returned invalid JSON") from exc
    if not isinstance(response, dict):
        raise RuntimeError("Mac Brain response was not a JSON object")
    return response


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Synchronous external controller for Mac Brain's inbound-only remote protocol."
    )
    parser.add_argument("--host", required=True, help="Mac Brain IPv4 address or trusted DNS name")
    parser.add_argument("--user", required=True, help="macOS SSH account on Mac Brain")
    parser.add_argument("--identity", required=True, help="dedicated private SSH key path")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--request-id")
    sub = parser.add_subparsers(dest="op", required=True)
    sub.add_parser("ping")
    sub.add_parser("status")
    sub.add_parser("proposals")
    ask = sub.add_parser("ask")
    ask.add_argument("prompt")

    args = parser.parse_args(argv)
    prompt = args.prompt if args.op == "ask" else None
    try:
        request = build_request(args.op, prompt=prompt, request_id=args.request_id)
        response = call_macbrain(
            host=args.host,
            user=args.user,
            identity_file=args.identity,
            request=request,
            port=args.port,
            timeout_seconds=args.timeout,
        )
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if response.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
