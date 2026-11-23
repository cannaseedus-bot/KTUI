"""Host adapter for the K'UHUL phase engine package (v0.1.0).

That package ships itself as a *declarative contract*, not an engine — its README says so, and its
own test suite does not pass as delivered. So this adapter treats it as data and does only what the
package asks of a host:

  - verify a bank's SHA-256 against `manifest.json` before trusting the file,
  - learn the phase banks into the *existing* AIML kernel as candidates (no second compiler),
  - report pattern collisions with our own banks so precedence is explicit, not accidental,
  - read the phase order from the contract instead of hardcoding it.

It never executes anything on a phase's behalf, and a phase declaration grants no I/O. Tool calls,
task-list mutations and file writes still go through the sandbox, the planner and `/allow`.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Iterable, Sequence

APP_ROOT = Path(__file__).resolve().parent
ROOT = APP_ROOT / "kuhul-phase-engine-v0.1.0"
MANIFEST = ROOT / "manifest.json"
CONTRACT = ROOT / "registry" / "phase-contract.json"

CATEGORY = re.compile(r"<category\b", re.I)
PATTERN = re.compile(r"<pattern>(.*?)</pattern>", re.S | re.I)


def available() -> bool:
    return MANIFEST.is_file()


def manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def phase_order() -> tuple[str, ...]:
    """The contract is the authority; the manifest is the fallback."""
    try:
        order = json.loads(CONTRACT.read_text(encoding="utf-8")).get("order") or []
    except (OSError, ValueError):
        order = []
    return tuple(str(phase) for phase in order) or tuple(manifest().get("phase_order") or ())


def _key(phase: str) -> str:
    """`Ch'en` -> `chen`: the contract spells it with an apostrophe, the manifest does not."""
    return phase.lower().replace("'", "").replace("\u2019", "")


def banks() -> tuple[tuple[str, Path], ...]:
    """Phase banks in cycle order, then routing and integrations, as labelled paths."""
    found: list[tuple[str, Path]] = []
    files = manifest().get("phase_files") or {}
    for phase in phase_order():
        relative = files.get(_key(phase))
        if relative:
            found.append((phase, ROOT / relative))
    for phase, relative in files.items():
        if not any(_key(label) == _key(phase) for label, _ in found):
            found.append((phase.capitalize(), ROOT / relative))
    for relative in manifest().get("routing") or []:
        found.append((Path(relative).stem, ROOT / relative))
    for relative in manifest().get("integrations") or []:
        found.append((Path(relative).stem, ROOT / relative))
    return tuple(found)


def digest_of(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_digest(relative: Path | str) -> str | None:
    return (manifest().get("source_sha256") or {}).get(Path(relative).as_posix())


def trusted(path: Path) -> bool:
    """A bank is loaded only when its digest matches the manifest. An absent digest is not trust."""
    path = Path(path)
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        return False
    wanted = expected_digest(relative)
    if not wanted:
        return False
    try:
        return digest_of(path) == wanted
    except OSError:
        return False


def categories(path: Path) -> int:
    try:
        return len(CATEGORY.findall(Path(path).read_text(encoding="utf-8", errors="replace")))
    except OSError:
        return 0


def patterns(path: Path) -> set[str]:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return {" ".join(match.split()).upper() for match in PATTERN.findall(text)}


def verify() -> dict:
    """What is here, what is trusted, and what could not be read."""
    report = {
        "present": available(),
        "order": phase_order(),
        "banks": [],
        "bad_digest": [],
        "missing": [],
        "categories": 0,
    }
    if not report["present"]:
        report["missing"].append(str(MANIFEST))
        return report
    for label, path in banks():
        if not path.is_file():
            report["missing"].append(path.relative_to(ROOT).as_posix())
            continue
        if not trusted(path):
            report["bad_digest"].append(path.relative_to(ROOT).as_posix())
        count = categories(path)
        report["categories"] += count
        report["banks"].append({"phase": label, "file": path.relative_to(ROOT).as_posix(), "categories": count})
    return report


def load_order(others: Sequence[Path] = ()) -> tuple[tuple[str, Path], ...]:
    """Only the trusted banks, in cycle order: they are learned before the host's own banks."""
    return tuple((label, path) for label, path in banks() if path.is_file() and trusted(path))


def collisions(host_paths: Iterable[Path]) -> list[dict]:
    """Patterns declared by both a phase bank and one of our banks — precedence must be explicit.

    We learn the phase banks first and our own banks last, so ours win; this report is how that
    choice stays visible instead of surprising someone mid-conversation.
    """
    ours: dict[str, str] = {}
    for path in host_paths:
        path = Path(path)
        for pattern in patterns(path):
            ours.setdefault(pattern, path.name)
    found = []
    for label, path in load_order():
        if not path.is_file():
            continue
        for pattern in sorted(patterns(path) & ours.keys()):
            found.append({"pattern": pattern, "phase_bank": f"{label}:{path.name}", "host_bank": ours[pattern]})
    return sorted(found, key=lambda row: (row["pattern"], row["phase_bank"]))


def summary(host_paths: Iterable[Path] = ()) -> str:
    """The `/phase` report: integrity first, then what precedence will do."""
    report = verify()
    if not report["present"]:
        return "The K'UHUL phase package is not present (kuhul-phase-engine-v0.1.0/manifest.json)."
    lines = [
        f"K'UHUL phase package · {ROOT.name}",
        f"cycle: {' → '.join(report['order'])}",
        f"banks: {len(report['banks'])} · categories: {report['categories']}",
    ]
    if report["bad_digest"]:
        lines.append("digest mismatch (not loaded): " + ", ".join(report["bad_digest"]))
    if report["missing"]:
        lines.append("missing: " + ", ".join(report["missing"]))
    for row in report["banks"]:
        lines.append(f"  {row['phase']:<8} {row['file']:<32} {row['categories']} categories")
    found = collisions(host_paths)
    if found:
        lines.append("")
        lines.append(f"{len(found)} pattern collision(s) with our own banks — ours are learned last, so ours win:")
        for row in found[:12]:
            lines.append(f"  {row['pattern']}  ({row['phase_bank']} vs {row['host_bank']})")
        if len(found) > 12:
            lines.append(f"  … {len(found) - 12} more")
    else:
        lines.append("no pattern collisions with codex.aiml or _override.aiml")
    lines.append("")
    lines.append("Data only: the phase banks are candidates, not permissions. Tool calls still go")
    lines.append("through the sandbox and the planner, and writes still need `/allow`.")
    return "\n".join(lines)
