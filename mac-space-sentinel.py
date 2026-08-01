#!/usr/bin/env python3
"""Mac Space Sentinel: conservative, agent-friendly macOS disk analysis.

The scanner never deletes, moves, installs software, or follows symlinks.  The
separate plan executor only moves explicitly approved paths to the Trash.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import plistlib
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
import shlex
from pathlib import Path
from typing import Any

APP = "mac-space-sentinel"
VERSION = "0.1.0"
HOME = Path.home().resolve()
DEFAULT_ROOT = Path("/System/Volumes/Data")
PROTECTED_PREFIXES = (Path("/System"), Path("/private"), Path("/usr"), Path("/bin"), Path("/sbin"), Path("/Applications"))
PROTECTED_HOME_PARTS = {".ssh", ".gnupg", ".Trash", "Library/Keychains", "Library/Mobile Documents"}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def run(command: list[str], timeout: int = 30) -> dict[str, Any]:
    try:
        p = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
        return {"command": command, "returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": command, "returncode": None, "stdout": "", "stderr": str(exc)}


def bytes_human(value: int | float) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(value)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def sha256_file(path: Path) -> str:
    digest = __import__("hashlib").sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tool_status() -> dict[str, Any]:
    optional = {name: shutil.which(name) for name in ("gdu", "ncdu", "tree", "jq", "sqlite3", "brew")}
    required = {name: shutil.which(name) for name in ("python3", "diskutil", "df", "du")}
    return {"required": required, "optional": optional, "all_required_present": all(required.values())}


def apfs_info() -> dict[str, Any]:
    raw = run(["diskutil", "apfs", "list", "-plist"], timeout=20)
    info: dict[str, Any] = {"raw_status": raw["returncode"]}
    if raw["returncode"] == 0:
        try:
            plist = plistlib.loads(raw["stdout"].encode())
            info["containers"] = plist.get("Containers", [])
        except Exception as exc:
            info["parse_error"] = str(exc)
    return info


def filesystem_info(path: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(path)
    return {"path": str(path), "total_bytes": usage.total, "used_bytes": usage.used,
            "free_bytes": usage.free, "free_ratio": round(usage.free / usage.total, 4)}


def top_level_usage(root: Path, cross_filesystems: bool) -> tuple[list[dict[str, Any]], list[str]]:
    """Use native du for inclusive directory sizes without loading all children."""
    entries: list[Path] = []
    device = root.stat().st_dev
    for child in root.iterdir():
        try:
            if child.is_symlink() or (not cross_filesystems and child.stat(follow_symlinks=False).st_dev != device):
                continue
            entries.append(child)
        except OSError:
            continue
    result: list[dict[str, Any]] = []
    errors: list[str] = []
    for child in entries:
        outcome = run(["du", "-sk" if cross_filesystems else "-skx", str(child)], timeout=120)
        if outcome["returncode"] != 0 or not outcome["stdout"].strip():
            errors.append(f"recursive usage omitted for {child}: {outcome['stderr'].strip() or 'du failed or timed out'}")
            continue
        try:
            kib = int(outcome["stdout"].split("\t", 1)[0])
        except ValueError:
            continue
        size = kib * 1024
        result.append({"path": str(logical_path(child)), "bytes": size, "human": bytes_human(size), "category": classify(child)})
    return sorted(result, key=lambda x: x["bytes"], reverse=True), errors


def classify(path: Path) -> str:
    text = str(path)
    parts = set(path.parts)
    if "Caches" in parts or ".cache" in parts:
        return "cache"
    if "Downloads" in parts:
        return "downloads"
    if "Movies" in parts or "Pictures" in parts or "Music" in parts:
        return "media"
    if "node_modules" in parts:
        return "dependency-tree"
    if ".git" in parts:
        return "git-data"
    for marker, label in (("/Library/Developer/", "developer-artifacts"), ("/Library/Caches/", "cache"),
                          ("/.cache/", "cache"), ("/Downloads/", "downloads"),
                          ("/Movies/", "media"), ("/Pictures/", "media"), ("/Music/", "media"),
                          ("/.Trash/", "trash"), ("/node_modules/", "dependency-tree"),
                          ("/.git/", "git-data")):
        if marker in text:
            return label
    return "other"


def logical_path(path: Path) -> Path:
    """Translate the physical Data-volume prefix into the normal macOS path."""
    data = Path("/System/Volumes/Data")
    try:
        return Path("/") / path.resolve().relative_to(data)
    except (ValueError, OSError):
        return path.resolve()


def safe_relative(path: Path) -> str | None:
    try:
        return str(logical_path(path).relative_to(HOME))
    except (ValueError, OSError):
        return None


def scan(root: Path, min_file_bytes: int, max_files: int, top_n: int, exclude: list[Path], cross_filesystems: bool = False) -> dict[str, Any]:
    root = root.resolve()
    excluded = [p.resolve() for p in exclude]
    top_files: list[dict[str, Any]] = []
    directories: dict[str, int] = {}
    errors: list[str] = []
    count = 0
    started = time.monotonic()
    root_device = root.stat().st_dev

    def is_excluded(p: Path) -> bool:
        return any(p == x or x in p.parents for x in excluded)

    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False, onerror=lambda e: errors.append(str(e))):
        current_path = Path(current)
        kept: list[str] = []
        for d in dirnames:
            candidate = current_path / d
            try:
                different_filesystem = candidate.stat(follow_symlinks=False).st_dev != root_device
            except OSError as exc:
                errors.append(f"{candidate}: {exc}")
                continue
            if not is_excluded(candidate) and not candidate.is_symlink() and (cross_filesystems or not different_filesystem):
                kept.append(d)
        dirnames[:] = kept
        total_here = 0
        for name in filenames:
            if count >= max_files:
                break
            path = current_path / name
            try:
                stat = path.stat(follow_symlinks=False)
            except OSError as exc:
                if len(errors) < 200:
                    errors.append(f"{path}: {exc}")
                continue
            count += 1
            total_here += stat.st_size
            if stat.st_size >= min_file_bytes:
                item = {"path": str(logical_path(path)), "bytes": stat.st_size, "modified_ns": stat.st_mtime_ns, "human": bytes_human(stat.st_size),
                        "modified": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).isoformat(),
                        "category": classify(path), "inside_home": safe_relative(path) is not None}
                top_files.append(item)
        if total_here:
            directories[str(current_path)] = directories.get(str(current_path), 0) + total_here
        if count >= max_files:
            errors.append(f"scan stopped at --max-files={max_files}")
            break
    top_files.sort(key=lambda x: x["bytes"], reverse=True)
    top_dirs = sorted(({"path": str(logical_path(Path(p))), "bytes": b, "human": bytes_human(b), "category": classify(Path(p))}
                       for p, b in directories.items()), key=lambda x: x["bytes"], reverse=True)[:top_n]
    recursive_dirs, usage_errors = top_level_usage(root, cross_filesystems)
    return {"root": str(root), "files_seen": count, "elapsed_seconds": round(time.monotonic() - started, 2),
            "large_files": top_files[:top_n], "top_directories_direct_files_only": top_dirs,
            "top_level_directories_recursive": recursive_dirs,
            "errors": (errors + usage_errors)[:200], "incomplete": count >= max_files}


def recommendations(fs: dict[str, Any], inventory: dict[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    if fs["free_ratio"] < 0.15:
        result.append({"priority": "high", "kind": "capacity", "message": "Free physical APFS capacity is below 15%; target at least 40-50 GiB of actual free space."})
    categories = {x["category"] for x in inventory["large_files"]}
    if "cache" in categories:
        result.append({"priority": "review", "kind": "cache", "message": "Large cache artifacts found. Inspect their owning app; do not delete active build or browser data blindly."})
    if "downloads" in categories:
        result.append({"priority": "review", "kind": "downloads", "message": "Large Downloads files are good candidates for manual retain/archive/trash decisions."})
    if "developer-artifacts" in categories or "dependency-tree" in categories:
        result.append({"priority": "review", "kind": "developer", "message": "Developer artifacts found. Prefer project-specific clean commands or rebuildable-cache cleanup after verifying the project."})
    if not result:
        result.append({"priority": "normal", "kind": "capacity", "message": "No immediate automatic action is recommended; inspect ranked paths and make an explicit plan."})
    return result


def init_db(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS scans (id TEXT PRIMARY KEY, created_at TEXT, root TEXT, report_json TEXT);
    CREATE TABLE IF NOT EXISTS large_files (scan_id TEXT, path TEXT, bytes INTEGER, category TEXT, modified TEXT);
    """)
    return db


def write_json_limited(path: Path, value: dict[str, Any], max_bytes: int) -> None:
    raw = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if len(raw) > max_bytes:
        raise SystemExit(f"Refusing report write: artifact would exceed {max_bytes} bytes.")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)


def write_report(args: argparse.Namespace) -> Path:
    root = Path(args.root).expanduser()
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Scan root is not a directory: {root}")
    out = Path(args.output).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    fs = filesystem_info(root)
    low_space = fs["free_bytes"] < 15 * 1024**3 or fs["free_ratio"] < 0.15
    profile = "low-space" if args.profile == "auto" and low_space else args.profile
    effective_max_files = min(args.max_files, 100_000) if profile == "low-space" else args.max_files
    effective_top = min(args.top, 100) if profile == "low-space" else args.top
    scan_id = str(uuid.uuid4())
    inventory = scan(root, args.min_file_mib * 1024 * 1024, effective_max_files, effective_top,
                     [Path(p).expanduser() for p in args.exclude], args.cross_filesystems)
    report = {"schema_version": 1, "app": APP, "version": VERSION, "scan_id": scan_id, "created_at": now(),
              "safety": {"scan_is_read_only": True, "yolo_means": "produce plan only; it never applies actions",
                         "profile": profile, "low_space": low_space, "artifact_budget_bytes": args.max_artifact_mib * 1024 * 1024},
              "tooling": tool_status(), "filesystem": fs, "apfs": apfs_info(), "inventory": inventory,
              "recommendations": recommendations(fs, inventory)}
    json_path = out / f"report-{scan_id}.json"
    write_json_limited(json_path, report, args.max_artifact_mib * 1024 * 1024)
    if not args.no_history and profile != "low-space":
        db = init_db(out / "history.sqlite3")
        db.execute("INSERT INTO scans VALUES (?, ?, ?, ?)", (scan_id, report["created_at"], str(root), json.dumps(report)))
        db.executemany("INSERT INTO large_files VALUES (?, ?, ?, ?, ?)", [(scan_id, x["path"], x["bytes"], x["category"], x["modified"]) for x in inventory["large_files"]])
        db.commit(); db.close()
    plan = {"schema": "mac-space-sentinel.trash-plan/v1", "kind": "trash-plan", "created_from_scan": scan_id,
            "source_report": str(json_path), "source_report_sha256": sha256_file(json_path), "created_at": now(),
            "safety_contract": "Actions are empty by design. Copy only reviewed candidate path, bytes, and modified_ns. Executor moves, never deletes.",
            "actions": [], "review_candidates": inventory["large_files"][:min(20, len(inventory["large_files"]))]}
    plan_path = out / f"review-plan-{scan_id}.json"
    write_json_limited(plan_path, plan, args.max_artifact_mib * 1024 * 1024)
    print(json.dumps({"report": str(json_path), "database": None if args.no_history or profile == "low-space" else str(out / "history.sqlite3"), "review_plan": str(plan_path), "files_seen": inventory["files_seen"], "incomplete": inventory["incomplete"], "profile": profile}, ensure_ascii=False))
    return json_path


def assessment_template(report: dict[str, Any], report_path: Path) -> dict[str, Any]:
    inventory = report["inventory"]
    evidence = [{"id": f"dir-{i}", "path": x["path"], "bytes": x["bytes"], "category": x["category"]}
                for i, x in enumerate(inventory.get("top_level_directories_recursive", [])[:20], 1)]
    photos = [x for x in inventory.get("large_files", []) if ".photoslibrary" in x.get("path", "")]
    actions: list[dict[str, Any]] = []
    cache_ids = [x["id"] for x in evidence if x["category"] == "cache"]
    if cache_ids:
        actions.append({"id": "inspect-cache", "kind": "drilldown", "risk": "review", "evidence_ids": cache_ids,
                        "title": "Analizza cache per applicazione", "detail": "Non elimina nulla; misura prima le sotto-cartelle."})
    if photos:
        actions.append({"id": "photos-icloud-guidance", "kind": "guided-settings", "risk": "human-confirmation", "evidence_ids": [],
                        "title": "Valuta Foto di iCloud e Ottimizza spazio Mac", "detail": "Apre Foto; non modifica la libreria né attiva impostazioni automaticamente."})
    return {"schema": "mac-space-sentinel.assessment/v1", "report": str(report_path), "report_sha256": sha256_file(report_path),
            "created_at": now(), "headline": "Valutazione storage pronta per revisione", "evidence": evidence,
            "findings": [], "actions": actions, "questions": ["Quale area vuoi esaminare prima?"],
            "constraints": ["Le stime non autorizzano cancellazioni.", "Foto e iCloud richiedono conferma umana."]}


def assessment_command(args: argparse.Namespace) -> None:
    report_path = Path(args.report).expanduser().resolve(strict=True)
    packet = assessment_template(json.loads(report_path.read_text()), report_path)
    if args.output:
        write_json_limited(Path(args.output).expanduser(), packet, args.max_artifact_mib * 1024 * 1024)
    print(json.dumps(packet, ensure_ascii=False, indent=2))


def validate_assessment(packet: dict[str, Any], report_path: Path) -> None:
    required = {"schema", "report", "report_sha256", "created_at", "headline", "evidence", "findings", "actions", "questions", "constraints"}
    if set(packet) != required or packet.get("schema") != "mac-space-sentinel.assessment/v1":
        raise ValueError("assessment_schema_mismatch")
    if Path(packet.get("report", "")).expanduser().resolve() != report_path or packet.get("report_sha256") != sha256_file(report_path):
        raise ValueError("assessment_report_binding_invalid")
    expected = assessment_template(json.loads(report_path.read_text()), report_path)
    if packet["evidence"] != expected["evidence"]:
        raise ValueError("assessment_evidence_mismatch")
    allowed_actions = {x["id"] for x in expected["actions"]}
    if not all(isinstance(x, dict) and x.get("id") in allowed_actions for x in packet["actions"]):
        raise ValueError("assessment_action_not_allowed")
    if not isinstance(packet["headline"], str) or len(packet["headline"]) > 240:
        raise ValueError("assessment_headline_invalid")
    evidence_ids = {x["id"] for x in packet["evidence"]}
    for finding in packet["findings"]:
        if not isinstance(finding, dict) or set(finding) != {"id", "evidence_ids", "statement", "confidence"} or not isinstance(finding["statement"], str) or len(finding["statement"]) > 1000 or not isinstance(finding["evidence_ids"], list) or not set(finding["evidence_ids"]).issubset(evidence_ids):
            raise ValueError("assessment_finding_invalid")


def tui(args: argparse.Namespace) -> None:
    if args.open_terminal:
        command = f"cd {shlex.quote(str(Path(__file__).parent))} && {shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__)))} tui --report {shlex.quote(args.report)}"
        if args.assessment:
            command += f" --assessment {shlex.quote(args.assessment)}"
        subprocess.run(["osascript", "-e", f"tell application \"Terminal\" to do script {json.dumps(command)}"], check=False)
        return
    report_path = Path(args.report).expanduser().resolve(strict=True)
    report = json.loads(report_path.read_text())
    packet = json.loads(Path(args.assessment).expanduser().read_text()) if args.assessment else assessment_template(report, report_path)
    validate_assessment(packet, report_path)
    print(f"\n{APP.upper()} — {packet['headline']}")
    fs = report["filesystem"]
    print(f"Spazio libero: {bytes_human(fs['free_bytes'])} ({fs['free_ratio']:.1%}) | Profilo: {report['safety'].get('profile', 'normal')}")
    for index, action in enumerate(packet.get("actions", []), 1):
        print(f"[{index}] {action['title']} — {action['detail']} ({action['risk']})")
    print("[0] Esci senza decisioni")
    if not sys.stdin.isatty():
        return
    choice = input("Selezione: ").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(packet.get("actions", [])):
        return
    action = packet["actions"][int(choice) - 1]
    if input(f"Confermi '{action['title']}'? [y/N] ").strip().lower() not in {"y", "yes"}:
        return
    decision = {"schema": "mac-space-sentinel.tui-decision/v1", "created_at": now(), "report": str(report_path), "action": action, "status": "approved_by_human"}
    decision_path = report_path.with_name(f"tui-decision-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
    write_json_limited(decision_path, decision, 1024 * 1024)
    if action["id"] == "photos-icloud-guidance":
        subprocess.run(["open", "-a", "Photos"], check=False)
    print(f"Decisione salvata: {decision_path}")


def validate_trash_target(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = HOME / path
    real = path.resolve(strict=True)
    try:
        relative = real.relative_to(HOME)
    except ValueError:
        raise ValueError(f"outside home directory: {real}")
    rel_text = str(relative)
    if any(rel_text == p or rel_text.startswith(p + "/") for p in PROTECTED_HOME_PARTS):
        raise ValueError(f"protected home path: {real}")
    if any(real == p or p in real.parents for p in PROTECTED_PREFIXES):
        raise ValueError(f"protected system path: {real}")
    return real


def preflight_plan(plan_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    plan = json.loads(plan_path.read_text())
    required = {"schema", "kind", "created_from_scan", "source_report", "source_report_sha256", "created_at", "safety_contract", "actions", "review_candidates"}
    if set(plan) != required or plan.get("schema") != "mac-space-sentinel.trash-plan/v1" or plan.get("kind") != "trash-plan" or not isinstance(plan.get("actions"), list):
        raise ValueError("plan_schema_mismatch")
    if not 0 < len(plan["actions"]) <= 50:
        raise ValueError("plan_action_count_invalid")
    report_path = Path(plan["source_report"]).expanduser().resolve(strict=True)
    if sha256_file(report_path) != plan["source_report_sha256"]:
        raise ValueError("source_report_hash_mismatch")
    report = json.loads(report_path.read_text())
    candidates = {x["path"]: x for x in report.get("inventory", {}).get("large_files", []) if isinstance(x, dict)}
    prepared: list[dict[str, Any]] = []
    seen: set[str] = set()
    for action in plan["actions"]:
        if not isinstance(action, dict) or set(action) != {"operation", "path", "expected_bytes", "expected_modified_ns"} or action.get("operation") != "move_to_trash":
            raise ValueError("action_schema_mismatch")
        if not isinstance(action["path"], str) or not isinstance(action["expected_bytes"], int) or not isinstance(action["expected_modified_ns"], int):
            raise ValueError("action_value_invalid")
        source = validate_trash_target(action["path"])
        if not source.is_file() or source.is_symlink():
            raise ValueError("action_target_not_regular_file")
        key = str(source)
        candidate = candidates.get(key)
        stat = source.stat()
        if key in seen or candidate is None or candidate.get("bytes") != action["expected_bytes"] or candidate.get("modified_ns") != action["expected_modified_ns"] or stat.st_size != action["expected_bytes"] or stat.st_mtime_ns != action["expected_modified_ns"]:
            raise ValueError("action_not_verified_scan_candidate")
        seen.add(key); prepared.append({"source": str(source), "bytes": stat.st_size, "modified_ns": stat.st_mtime_ns})
    return plan, prepared, sha256_file(plan_path)


def apply_plan(args: argparse.Namespace) -> None:
    if not args.yes_i_understand:
        raise SystemExit("Refusing: --yes-i-understand is mandatory for --apply-plan.")
    plan_path = Path(args.apply_plan).expanduser().resolve()
    try:
        plan, prepared, plan_hash = preflight_plan(plan_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Refusing invalid plan: {exc}")
    trash = HOME / ".Trash"
    trash.mkdir(exist_ok=True)
    if args.dry_run:
        receipt = {"schema": "mac-space-sentinel.dry-run-receipt/v1", "plan": str(plan_path), "plan_sha256": plan_hash,
                   "created_at": now(), "expires_at": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30)).replace(microsecond=0).isoformat(),
                   "approval_token": uuid.uuid4().hex, "targets": prepared, "consumed": False}
        receipt_path = plan_path.with_name(f"dry-run-receipt-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps({"dry_run": True, "receipt": str(receipt_path), "approval_token": receipt["approval_token"], "actions": len(prepared)})); return
    if not args.receipt:
        raise SystemExit("Refusing: create a fresh --dry-run receipt, then pass --receipt for execution.")
    receipt_path = Path(args.receipt).expanduser().resolve(strict=True)
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("schema") != "mac-space-sentinel.dry-run-receipt/v1" or receipt.get("plan_sha256") != plan_hash or receipt.get("consumed") is not False or receipt.get("targets") != prepared or dt.datetime.fromisoformat(receipt["expires_at"]) <= dt.datetime.now(dt.timezone.utc):
        raise SystemExit("Refusing: receipt is invalid, stale, consumed, or does not bind this exact plan.")
    journal: list[dict[str, str]] = []
    moved: list[tuple[Path, Path]] = []
    try:
      for item in prepared:
        source = Path(item["source"])
        destination = trash / source.name
        if destination.exists():
            destination = trash / f"{source.name}.{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
        shutil.move(str(source), str(destination)); moved.append((source, destination)); journal.append({"moved": str(source), "to": str(destination)})
    except OSError as exc:
        for source, destination in reversed(moved):
            if destination.exists() and not source.exists(): shutil.move(str(destination), str(source))
        raise SystemExit(f"Execution failed; prior moves were rolled back: {exc}")
    receipt["consumed"] = True; receipt["consumed_at"] = now(); receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    result = {"schema": "mac-space-sentinel.execution-journal/v1", "created_at": now(), "plan": str(plan_path), "plan_sha256": plan_hash, "journal": journal}
    journal_path = plan_path.with_name(f"execution-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
    journal_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"journal": str(journal_path), "actions": len(journal)}, ensure_ascii=False))


def doctor(args: argparse.Namespace) -> None:
    status = tool_status()
    print(json.dumps(status, indent=2, ensure_ascii=False))
    missing = [name for name, value in status["optional"].items() if value is None and name != "brew"]
    if args.install_tools and missing:
        brew = status["optional"].get("brew")
        if not brew:
            raise SystemExit("Homebrew is not available; install optional tools manually.")
        if not sys.stdin.isatty():
            raise SystemExit("Refusing to install tools without an interactive TTY.")
        answer = input(f"Install optional tools with Homebrew ({', '.join(missing)})? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("No tools installed."); return
        subprocess.run([brew, "install", *missing], check=False)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Conservative macOS disk scanner and review-plan executor.")
    p.add_argument("--version", action="version", version=f"{APP} {VERSION}")
    sub = p.add_subparsers(dest="command", required=True)
    d = sub.add_parser("doctor", help="check native/optional analysis tools")
    d.add_argument("--install-tools", action="store_true", help="ask in an interactive TTY before Homebrew installs missing optional tools")
    d.set_defaults(func=doctor)
    s = sub.add_parser("scan", help="read-only inventory; writes JSON and SQLite reports")
    s.add_argument("--root", default=str(DEFAULT_ROOT), help="directory to inventory (default: Data volume)")
    s.add_argument("--output", default="./reports", help="report directory")
    s.add_argument("--top", type=int, default=200, help="maximum ranked entries")
    s.add_argument("--min-file-mib", type=int, default=256, help="only record individual files at least this size")
    s.add_argument("--max-files", type=int, default=1_000_000, help="hard scan cap; report is marked incomplete if hit")
    s.add_argument("--profile", choices=("auto", "normal", "low-space"), default="auto", help="auto uses bounded low-space mode below 15 GiB or 15%% free")
    s.add_argument("--max-artifact-mib", type=int, default=5, help="hard maximum size for each JSON artifact")
    s.add_argument("--no-history", action="store_true", help="do not write SQLite history")
    s.add_argument("--exclude", action="append", default=["/System/Volumes/Data/private/var/vm"], help="path to skip; repeatable")
    s.add_argument("--cross-filesystems", action="store_true", help="also traverse mounted external/network volumes (off by default)")
    s.add_argument("--yolo", action="store_true", help="compatibility mode: still scan/plan only; never applies actions")
    s.set_defaults(func=write_report)
    a = sub.add_parser("apply", help="move explicitly reviewed plan items to Trash")
    a.add_argument("--apply-plan", required=True)
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--receipt", help="fresh dry-run receipt required for a real execution")
    a.add_argument("--yes-i-understand", action="store_true")
    a.set_defaults(func=apply_plan)
    assess = sub.add_parser("assessment-template", help="emit evidence-bound packet for an LLM or TUI")
    assess.add_argument("--report", required=True)
    assess.add_argument("--output")
    assess.add_argument("--max-artifact-mib", type=int, default=1)
    assess.set_defaults(func=assessment_command)
    t = sub.add_parser("tui", help="show human decisions in this Terminal or a separate Terminal window")
    t.add_argument("--report", required=True)
    t.add_argument("--assessment")
    t.add_argument("--open-terminal", action="store_true", help="open this TUI in a separate macOS Terminal window")
    t.set_defaults(func=tui)
    return p


if __name__ == "__main__":
    args = parser().parse_args()
    args.func(args)
