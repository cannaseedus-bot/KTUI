"""Independent, restorable backups of this repository.

A branch is a mutable reference: a force-push or a bad rebase can leave history unreachable, which is
exactly what happened here once. These backups are content-addressed instead: one bundle containing
every ref, plus a manifest of SHA-256 digests, plus an append to the audit ledger so the *set* of
backups is itself a chain.

"Restorable" means verified, not merely written: `verify()` runs `git bundle verify`, clones the
bundle into a temporary directory, checks the expected commit is there, and can run the suites from
the clone. A backup nobody has restored is a hope.

The files are written where the caller asks. Inside the workspace they land under `backups/`, which
git ignores - a backup that lives in the history it protects is not a backup. Copy that directory
somewhere else (another disk, another machine) to get the off-machine property; nothing here can
promise that for you.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
DEFAULT_DEST = APP_ROOT / "backups"


def _run(args, cwd, timeout=300):
    result = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def head(repo: Path = APP_ROOT) -> dict:
    code, out, _ = _run(["git", "rev-parse", "HEAD"], repo)
    if code != 0:
        raise RuntimeError(f"{repo} is not a git repository")
    sha = out
    code, branch, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo)
    code, refs, _ = _run(["git", "for-each-ref", "--format=%(refname) %(objectname)"], repo)
    return dict(sha=sha, branch=branch,
                refs=[line.split(" ", 1) for line in refs.splitlines() if line.strip()])


def create(dest: Path = DEFAULT_DEST, *, repo: Path = APP_ROOT, ledger: bool = True,
           ledger_path: Path | None = None) -> dict:
    """Bundle every ref, hash it into a manifest, and record the backup in the audit ledger."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    info = head(repo)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bundle = dest / f"ktui-{info['sha'][:12]}-{stamp}.bundle"
    code, out, err = _run(["git", "bundle", "create", str(bundle), "--all"], repo)
    if code != 0 or not bundle.is_file():
        raise RuntimeError(f"git bundle create failed: {err or out}")
    entry = dict(bundle=bundle.name, sha256=_sha256(bundle), bytes=bundle.stat().st_size,
                 head=info["sha"], branch=info["branch"], refs=len(info["refs"]),
                 created_at=datetime.now(timezone.utc).isoformat())
    manifest = dest / "manifest.json"
    document = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else dict(backups=[])
    document["backups"].append(entry)
    document["updated_at"] = entry["created_at"]
    manifest.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    if ledger:
        try:
            import ledger_plugin
            ledger_plugin.append({"kind": "backup", "payload": dict(entry)},
                                 ledger_path or ledger_plugin.LEDGER_PATH)
        except Exception as error:  # a backup is still a backup if the ledger is unavailable
            print(f"warning: ledger append skipped ({error})", file=sys.stderr)
    return dict(entry=entry, path=str(bundle), manifest=str(manifest))


def verify(bundle: Path, *, expect_commit: str | None = None, run_suites: bool = False,
           timeout: int = 600) -> dict:
    """Bundle-verify, clone into a temporary directory, and check what came back."""
    bundle = Path(bundle)
    reasons = []
    if not bundle.is_file():
        return dict(ok=False, reasons=[dict(code="missing", detail=str(bundle))])
    # `git bundle verify` needs *a* repository to resolve prerequisites; any clone will do, so it
    # runs here rather than in the backup directory (which is not a repository).
    code, out, err = _run(["git", "bundle", "verify", str(Path(bundle).resolve())], APP_ROOT)
    if code != 0:
        reasons.append(dict(code="bundle_verify", detail=(err or out)[:400]))
    with tempfile.TemporaryDirectory() as folder:
        clone = Path(folder) / "restored"
        code, out, err = _run(["git", "clone", "--quiet", str(bundle), str(clone)], folder, timeout)
        if code != 0:
            reasons.append(dict(code="clone_failed", detail=(err or out)[:400]))
            return dict(ok=False, reasons=reasons, restored=str(bundle))
        code, restored_head, _ = _run(["git", "rev-parse", "HEAD"], clone)
        code, count, _ = _run(["git", "rev-list", "--count", "--all"], clone)
        files = sum(1 for path in clone.rglob("*") if path.is_file() and ".git" not in path.parts)
        if expect_commit and restored_head != expect_commit:
            reasons.append(dict(code="commit_mismatch",
                                detail=f"restored {restored_head} != expected {expect_commit}"))
        suites = {}
        if run_suites:
            package = clone / "kuhul-phase-engine-v0.1.0"
            for label, cwd, command in (
                    ("package", package, [sys.executable, "-m", "unittest", "discover", "-s", "tests"]),
                    ("host", clone, [sys.executable, "-m", "unittest", "discover", "-s", "tests_host"])):
                if not cwd.is_dir():
                    suites[label] = dict(ok=False, reason="directory missing in the restore")
                    continue
                code, out, err = _run(command, cwd, timeout)
                suites[label] = dict(ok=code == 0, tail=(out or err).splitlines()[-3:])
                if code != 0:
                    reasons.append(dict(code=f"{label}_suite_failed", detail=(err or out)[-300:]))
    return dict(ok=not reasons, bundle=bundle.name, restored_head=restored_head,
                commits=int(count or 0), files=files, suites=suites, reasons=reasons)


def verify_latest(dest: Path = DEFAULT_DEST, **kwargs) -> dict:
    manifest = Path(dest) / "manifest.json"
    if not manifest.is_file():
        return dict(ok=False, reasons=[dict(code="no_manifest", detail=str(manifest))])
    document = json.loads(manifest.read_text(encoding="utf-8"))
    if not document.get("backups"):
        return dict(ok=False, reasons=[dict(code="no_backups", detail=str(manifest))])
    entry = document["backups"][-1]
    bundle = Path(dest) / entry["bundle"]
    digest_ok = bundle.is_file() and _sha256(bundle) == entry["sha256"]
    report = verify(bundle, expect_commit=entry["head"], **kwargs)
    report["manifest_digest_ok"] = digest_ok
    if not digest_ok:
        report["ok"] = False
        report.setdefault("reasons", []).append(
            dict(code="manifest_digest_mismatch", detail=f"{bundle.name} does not match its recorded sha256"))
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Create and verify independent repository backups.")
    parser.add_argument("--to", type=Path, default=DEFAULT_DEST, help="backup directory")
    parser.add_argument("--verify", action="store_true", help="verify the newest backup in --to")
    parser.add_argument("--suites", action="store_true", help="run the suites from the restored clone")
    args = parser.parse_args(argv)
    if args.verify:
        report = verify_latest(args.to, run_suites=args.suites)
        print(json.dumps({key: value for key, value in report.items() if key != "reasons"}, indent=2))
        for reason in report.get("reasons") or []:
            print("  reason:", reason["code"], "-", reason["detail"][:160], file=sys.stderr)
        return 0 if report["ok"] else 1
    created = create(args.to)
    print(f"bundle:   {created['path']}")
    print(f"manifest: {created['manifest']}")
    report = verify(Path(created["path"]), expect_commit=created["entry"]["head"], run_suites=args.suites)
    print(json.dumps({key: value for key, value in report.items() if key != "reasons"}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
