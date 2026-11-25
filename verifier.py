"""One SHA-256 verifier file, locked. Not a security subsystem.

The review's ask, taken literally: a single `verifier.json` that locks a hash over the tracked source, updated only
when the source is updated. It answers "has anything changed since this was locked?" and nothing else.

    build()    hash every tracked source file, roll the digests into one manifest digest, write the lock
    verify()   recompute and report drift - changed, added, missing - without touching the file
    update()   the explicit, recorded way to re-lock, keeping the previous hash

Deliberately excluded from the hash, because they change on every run rather than when the code does: the verifier
itself, the gate artifacts, logs and backups. A lock that drifts on its own would be noise, not evidence.

The cryptographic ledger (`review_attestations`, `keymaker`) is a plugin for evaluation claims and is not required
here; nothing in this file imports it.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
SCHEMA = "kuhul://verifier/lock/v1"
LOCK = HOST_ROOT / "verifier.json"
EXCLUDED_PREFIXES = ("logs/", "backups/", "profiles/", ".git/")
EXCLUDED_NAMES = ("verifier.json", "evidence-gate.json")
EXCLUDED_GLOBS = ("host-gate-",)


class VerifierError(ValueError):
    """The lock cannot be built or read."""


def dirty_tracked() -> list[str]:
    """Tracked files with uncommitted changes - source the lock cannot certify."""
    completed = subprocess.run(["git", "status", "--porcelain", "-uno", "-z"], cwd=str(HOST_ROOT),
                               capture_output=True, timeout=60)
    if completed.returncode != 0:
        return []
    names = []
    for entry in completed.stdout.split(b"\0"):
        if not entry:
            continue
        text_entry = entry.decode("utf-8", "replace")
        name = text_entry[3:] if len(text_entry) > 3 else ""
        if name and _keep(name):
            names.append(name)
    return sorted(names)


def _keep(name: str) -> bool:
    normalized = name.replace("\\", "/")
    if normalized in EXCLUDED_NAMES or normalized.startswith(EXCLUDED_PREFIXES):
        return False
    return not any(normalized.startswith(prefix) for prefix in EXCLUDED_GLOBS)


def tracked_files() -> list[str]:
    """Every file git tracks, minus the ones that change per run."""
    try:
        completed = subprocess.run(["git", "ls-files", "-z"], cwd=str(HOST_ROOT), capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as error:
        raise VerifierError(f"git ls-files failed: {error}") from error
    if completed.returncode != 0:
        raise VerifierError(f"git ls-files failed: {completed.stderr.strip()[:200]}")
    return sorted(name for name in completed.stdout.split("\0") if name and _keep(name))


def digest_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _head_contents() -> dict[str, bytes]:
    """The committed bytes of every tracked file, read from HEAD in one batch.

    Hashing HEAD rather than the working tree is deliberate: a lock must not certify an uncommitted edit that
    happens to be lying around, and a tree is normally dirty while work is in progress.
    """
    listing = subprocess.run(["git", "ls-tree", "-r", "-z", "--full-tree", "HEAD"], cwd=str(HOST_ROOT),
                             capture_output=True, timeout=120)
    if listing.returncode != 0:
        raise VerifierError(f"git ls-tree failed: {listing.stderr.decode('utf-8', 'replace')[:200]}")
    entries = [entry for entry in listing.stdout.split(b"\0") if entry]
    wanted = []
    for entry in entries:
        header, _, path = entry.partition(b"\t")
        parts = header.split()
        if len(parts) >= 3 and parts[1] == b"blob":
            wanted.append((path.decode("utf-8", "replace"), parts[2].decode("ascii")))
    names = {name for name, _ in wanted}
    kept = [pair for pair in wanted if _keep(pair[0])]
    if not kept:
        return {}
    payload = b"\n".join(sha.encode("ascii") for _, sha in kept) + b"\n"
    batch = subprocess.run(["git", "cat-file", "--batch"], cwd=str(HOST_ROOT), input=payload,
                           capture_output=True, timeout=300)
    if batch.returncode != 0:
        raise VerifierError(f"git cat-file failed: {batch.stderr.decode('utf-8', 'replace')[:200]}")
    contents: dict[str, bytes] = {}
    stream = batch.stdout
    position = 0
    for name, _sha in kept:
        newline = stream.index(b"\n", position)
        header = stream[position:newline].split()
        size = int(header[2]) if len(header) >= 3 else 0
        start = newline + 1
        contents[name] = stream[start:start + size]
        position = start + size + 1          # content is followed by a newline
    return contents


def manifest(*, committed: bool = True) -> dict:
    """Path -> SHA-256 for every hashed file, plus the rolled digest.

    `committed=True` hashes HEAD (what was actually committed); `committed=False` hashes the working tree.
    """
    entries = {}
    if committed:
        for name, content in _head_contents().items():
            entries[name] = hashlib.sha256(content).hexdigest()
    else:
        for name in tracked_files():
            path = HOST_ROOT / name
            if path.is_file():
                entries[name] = digest_file(path)
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return dict(files=entries, hash=hashlib.sha256(canonical).hexdigest(), count=len(entries),
                source="HEAD" if committed else "working tree")


def build(*, lock: Path | None = None, note: str = "", force: bool = False) -> dict:
    lock = Path(lock or LOCK)
    dirty = dirty_tracked()
    if dirty and not force:
        # A lock written from a dirty tree certifies content nobody committed.
        raise VerifierError("refusing to lock a dirty tree: " + ", ".join(dirty[:5])
                            + (" ..." if len(dirty) > 5 else ""))
    current = manifest(committed=False)
    record = dict(schema=SCHEMA, algorithm="sha256", locked=True,
                  updated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  hash=current["hash"], files=current["files"], count=current["count"],
                  source=current["source"],
                  covers="tracked working tree; uncommitted edits are refused by verify()",
                  note=(note or "one hash over the tracked source; update it only when the source updates"),
                  excludes=dict(names=list(EXCLUDED_NAMES), prefixes=list(EXCLUDED_PREFIXES),
                                prefixes_by_name=list(EXCLUDED_GLOBS)),
                  optional_plugin=("the Ed25519 attestation ledger is an evaluation plugin; this lock does not "
                                   "depend on it"))
    lock.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def load(*, lock: Path | None = None) -> dict:
    lock = Path(lock or LOCK)
    try:
        record = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return dict(ok=False, refused="lock_missing", detail=str(error), record={})
    if record.get("schema") != SCHEMA:
        return dict(ok=False, refused="lock_schema", record=record)
    if record.get("algorithm") != "sha256":
        return dict(ok=False, refused="lock_algorithm", record=record)
    return dict(ok=True, refused=None, record=record)


def verify(*, lock: Path | None = None, ignore_dirty: bool = False) -> dict:
    """Compare the locked hash with the working tree. Reports drift; never rewrites the lock."""
    loaded = load(lock=lock)
    if not loaded["ok"]:
        return dict(ok=False, refused=loaded["refused"], detail=loaded.get("detail"),
                    drift={}, locked=None, current=None)
    locked = loaded["record"]
    current = manifest(committed=False)
    dirty = [] if ignore_dirty else dirty_tracked()
    if dirty:
        return dict(ok=False, refused="dirty_source", drift={}, locked=dict(hash=locked.get("hash")),
                    current=dict(hash=current["hash"], count=current["count"]), dirty=dirty,
                    locked_flag=bool(locked.get("locked")),
                    detail=("tracked source is uncommitted: " + ", ".join(dirty[:5])),
                    note="a lock cannot certify uncommitted source; commit or revert, then update the lock")
    locked_files = locked.get("files") or {}
    changed = sorted(name for name in locked_files
                     if name in current["files"] and locked_files[name] != current["files"][name])
    missing = sorted(name for name in locked_files if name not in current["files"])
    added = sorted(name for name in current["files"] if name not in locked_files)
    drift = dict(changed=changed, missing=missing, added=added)
    unchanged = not (changed or missing or added) and locked.get("hash") == current["hash"]
    return dict(ok=unchanged, refused=None if unchanged else "drift", drift=drift,
                locked=dict(hash=locked.get("hash"), count=locked.get("count"),
                            updated_at=locked.get("updated_at")),
                current=dict(hash=current["hash"], count=current["count"]),
                locked_flag=bool(locked.get("locked")),
                detail=None if unchanged else
                (f"{len(changed)} changed, {len(added)} added, {len(missing)} missing"))


def update(*, lock: Path | None = None, note: str = "", force: bool = False) -> dict:
    """Re-lock explicitly, keeping what the previous lock said so the change is traceable."""
    loaded = load(lock=lock)
    previous = dict(hash=(loaded.get("record") or {}).get("hash"),
                    count=(loaded.get("record") or {}).get("count"),
                    updated_at=(loaded.get("record") or {}).get("updated_at"))
    record = build(lock=lock, note=note, force=force)
    record["previous"] = previous
    Path(lock or LOCK).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def summary(report: dict) -> str:
    if report.get("refused") in ("lock_missing", "lock_schema", "lock_algorithm"):
        return f"verifier · {report['refused']} · {report.get('detail', '')}"
    if report["ok"]:
        return (f"verifier · locked and unchanged · {report['current']['count']} file(s) · "
                f"{report['current']['hash'][:16]}")
    if report.get("refused") == "dirty_source":
        return (f"verifier · DIRTY TREE · {len(report.get('dirty') or [])} uncommitted file(s) · "
                f"a lock cannot certify them · {report.get('detail') or ''}").strip()
    drift = report["drift"]
    return (f"verifier · DRIFT · {len(drift.get('changed') or [])} changed · "
            f"{len(drift.get('added') or [])} added · {len(drift.get('missing') or [])} missing · "
            f"locked {report['locked']['hash'][:16]} vs current {report['current']['hash'][:16]}")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Lock or check one SHA-256 over the tracked source.")
    parser.add_argument("command", choices=("build", "verify", "update"), nargs="?", default="verify")
    parser.add_argument("--note", default="")
    parser.add_argument("--force", action="store_true",
                        help="lock a dirty tree (records that it did)")
    args = parser.parse_args(argv)
    if args.command == "build":
        try:
            record = build(note=args.note, force=args.force)
        except VerifierError as error:
            print(f"refused: {error}")
            return 1
        print(f"locked · {record['count']} file(s) · {record['hash'][:16]}")
        return 0
    if args.command == "update":
        try:
            record = update(note=args.note, force=args.force)
        except VerifierError as error:
            print(f"refused: {error}")
            return 1
        print(f"re-locked · {record['count']} file(s) · {record['hash'][:16]} "
              f"(was {(record.get('previous') or {}).get('hash', 'none')}")
        return 0
    report = verify()
    print(summary(report))
    for name in (report.get("drift") or {}).get("changed", [])[:10]:
        print(f"  changed: {name}")
    for name in (report.get("drift") or {}).get("added", [])[:10]:
        print(f"  added:   {name}")
    for name in (report.get("drift") or {}).get("missing", [])[:10]:
        print(f"  missing: {name}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
