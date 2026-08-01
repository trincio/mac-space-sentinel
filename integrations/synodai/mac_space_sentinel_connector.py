#!/usr/bin/env python3
"""Host-owned, single-operation connector suitable for a future SYNODAI capability.

It deliberately offers no generic shell and no effectful Sentinel command.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REQUEST_SCHEMA = "mac-space-sentinel.connector-request/v1"
RESPONSE_SCHEMA = "mac-space-sentinel.connector-response/v1"
EXPECTED = {"schema", "operation", "root", "output_name", "min_file_mib", "top", "max_files"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate(request: dict[str, Any], allowed_roots: list[Path]) -> tuple[Path, str, list[str]]:
    if set(request) != EXPECTED or request.get("schema") != REQUEST_SCHEMA or request.get("operation") != "scan":
        raise ValueError("request_schema_mismatch")
    if not all(isinstance(request.get(key), int) and 0 < request[key] <= maximum for key, maximum in (("min_file_mib", 4096), ("top", 1000), ("max_files", 2_000_000))):
        raise ValueError("request_limits_invalid")
    output_name = request.get("output_name")
    if not isinstance(output_name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", output_name):
        raise ValueError("output_name_invalid")
    raw_root = request.get("root")
    if not isinstance(raw_root, str):
        raise ValueError("root_invalid")
    root = Path(raw_root).expanduser().resolve(strict=True)
    allowed_roots = [path.expanduser().resolve(strict=True) for path in allowed_roots]
    if not root.is_dir() or not any(within(root, allowed) for allowed in allowed_roots):
        raise ValueError("root_not_in_host_grant")
    return root, output_name, [str(x) for x in allowed_roots]


def execute(request: dict[str, Any], *, sentinel: Path, allowed_roots: list[Path], output_base: Path) -> dict[str, Any]:
    root, output_name, allowed = validate(request, allowed_roots)
    output = (output_base.resolve() / output_name).resolve()
    if not within(output, output_base.resolve()):
        raise ValueError("output_outside_host_sandbox")
    output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, str(sentinel), "scan", "--root", str(root), "--output", str(output),
               "--min-file-mib", str(request["min_file_mib"]), "--top", str(request["top"]),
               "--max-files", str(request["max_files"])]
    completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=600)
    if completed.returncode != 0:
        raise RuntimeError("sentinel_scan_failed")
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    report_path = Path(result["report"])
    report = json.loads(report_path.read_text())
    return {"schema": RESPONSE_SCHEMA, "operation": "scan", "status": "allowed", "allowed_roots": allowed,
            "report": str(report_path), "report_sha256": sha256(report_path), "scan_id": report["scan_id"],
            "files_seen": report["inventory"]["files_seen"], "incomplete": report["inventory"]["incomplete"],
            "executable_sha256": sha256(sentinel)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Host-only Mac Space Sentinel connector")
    parser.add_argument("--request", required=True)
    parser.add_argument("--allowed-root", action="append", required=True)
    parser.add_argument("--output-base", required=True)
    parser.add_argument("--sentinel", default=str(Path(__file__).parents[2] / "mac-space-sentinel.py"))
    args = parser.parse_args()
    try:
        request = json.loads(Path(args.request).read_text())
        if not isinstance(request, dict):
            raise ValueError("request_not_object")
        response = execute(request, sentinel=Path(args.sentinel).resolve(strict=True),
                           allowed_roots=[Path(p).expanduser().resolve(strict=True) for p in args.allowed_root],
                           output_base=Path(args.output_base))
        print(json.dumps(response, ensure_ascii=False))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"schema": RESPONSE_SCHEMA, "status": "denied", "rule": str(exc)}, ensure_ascii=False))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
