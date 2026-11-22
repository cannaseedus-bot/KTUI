"""Pattern dumper: turn prompt/response interactions into AIML categories.

Every task the terminal runs is already recorded in logs/gpt-oss-terminal/*.jsonl as a prompt and an
answer. This reads those pairs, compiles each one into an AIML `<category>` (pattern + template), and
appends it to the ALICE corpus — but only if that pattern is not already in the corpus, so running it
twice changes nothing and hand-written knowledge is never overwritten.

    python pattern_dumper.py dump            # append new categories
    python pattern_dumper.py dump --dry-run  # show what would be added
    python pattern_dumper.py dump --pair "what is the sandbox root" "the repository root"
    python pattern_dumper.py list            # what has been learned so far
    python pattern_dumper.py check           # duplicate patterns across the whole corpus

The generated file is `knumatic_learned.aiml` inside the corpus. It is generated data, not a hand-edited
file: the next dump appends to it, and `check` reports collisions rather than silently merging them.
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from pathlib import Path

try:  # sibling module; works when run as a script and when imported with this directory on the path
    from interaction_log import DEFAULT_DIR as DEFAULT_LOG_DIR, interaction_dirs, read_interactions
except ImportError:  # pragma: no cover - only if the file is moved away from its sibling
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from interaction_log import DEFAULT_DIR as DEFAULT_LOG_DIR, interaction_dirs, read_interactions
DEFAULT_CORPUS = Path(__file__).resolve().parent / "aiml-en-us-foundation-alice"
LEARNED_FILE = "knumatic_learned.aiml"

# A pattern has to be something a person could type, and short enough to be a rule rather than a
# paragraph. AIML matching is literal, so a 40-word sentence only ever matches itself.
MIN_WORDS = 2
MAX_WORDS = 14
MAX_PATTERN_CHARS = 160
MAX_TEMPLATE_CHARS = 2000

# Answers that mean "no answer": they must never become a template, or the bot learns to refuse.
# Note the absence of a trailing \b: "(no answer)" ends in a bracket, so a word boundary could never
# match after it, and the filter silently let refusals through as knowledge.
NON_ANSWERS = re.compile(
    r"^\s*(?:\(no answer\)|step[ _]limit|\(no answer\)|i (?:cannot|can't|do not know|don't know)|no answer|error:|refused)",
    re.IGNORECASE,
)

# XML text rules for a template: escape the markup characters, drop control characters that would make
# the document unparseable, and keep newlines (AIML templates may contain them).
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def normalize_pattern(text: str) -> str:
    """The AIML pattern form of a question: upper case, no punctuation, single spaces."""
    value = CONTROL_CHARS.sub(" ", str(text or ""))
    value = value.upper()
    value = re.sub(r"[^A-Z0-9*_\s]", " ", value)  # keep the wildcard characters
    value = re.sub(r"\s+", " ", value).strip()
    return value[:MAX_PATTERN_CHARS].strip()


def escape_template(text: str) -> str:
    value = CONTROL_CHARS.sub("", str(text or ""))
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# Terminal tasks are instructions ("read X, then answer: how many Y?"), not questions. Learning the
# whole sentence would produce a pattern that only ever matches that exact instruction, so the question
# clause is what gets learned: the last clause, starting at its interrogative or auxiliary.
QUESTION_STARTS = re.compile(
    r"\b(what|why|how|how many|how much|when|where|who|which|whose|is|are|was|were|do|does|did|can|could|should|would|will|list|show|explain|name|give)\b",
    re.IGNORECASE,
)
DIRECTIVE = re.compile(r"^(?:please\s+|kindly\s+)+", re.IGNORECASE)


def derive_pattern(task: str) -> str:
    """The learnable pattern for a task: the question clause, not the whole instruction."""
    normalized = normalize_pattern(task)
    if len(normalized.split()) <= MAX_WORDS:
        return normalized

    # Work on the last clause: instructions usually sit before a colon or a full stop.
    clause = re.split(r"[:?;]|\.\s|\bthen\b", normalized)[-1].strip()
    clause = DIRECTIVE.sub("", clause).strip()
    match = QUESTION_STARTS.search(clause)
    if match:
        clause = clause[match.start():].strip()
    if clause:
        return clause.strip()
    return normalized


def pattern_is_usable(pattern: str) -> tuple[bool, str]:
    if not pattern:
        return False, "empty after normalization"
    words = pattern.split()
    if len(words) < MIN_WORDS:
        return False, f"shorter than {MIN_WORDS} words"
    if len(words) > MAX_WORDS:
        return False, f"longer than {MAX_WORDS} words (matches only itself)"
    if pattern in {"*", "_"}:
        return False, "wildcard-only pattern would catch everything"
    return True, ""


def existing_patterns(corpus: Path) -> dict[str, str]:
    """Every pattern already in the corpus, normalized, mapped to the file that declares it."""
    found: dict[str, str] = {}
    if not corpus.is_dir():
        return found
    for file in sorted(corpus.glob("*.aiml")):
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in re.findall(r"<pattern>(.*?)</pattern>", text, flags=re.DOTALL):
            key = normalize_pattern(raw)
            if key and key not in found:
                found[key] = file.name
    return found


def interactions_from_logs(*directories: Path) -> list[dict]:
    """Prompt/response pairs from the shared interaction log and the terminal transcripts.

    Both `user`/`assistant` records (written by every client through interaction_log) and the older
    `task`/`answer` transcripts are accepted, so history is not lost when a client changes.
    """
    return read_interactions(*directories)


def compile_category(pattern: str, answer: str, *, provenance: str = "") -> str:
    """The AIML a pair compiles to, with a comment saying where it came from.

    The comment matters: a learned pair is a record of what a model said in one conversation, not a
    verified fact. AIML ignores comments, so this costs nothing at run time and is visible to anyone
    reading the corpus — including when a small model answered confidently and wrongly.
    """
    body = escape_template(answer).strip()
    note = f"    <!-- {provenance} -->\n" if provenance else ""
    return f"  <category>\n{note}    <pattern>{pattern}</pattern>\n    <template>{body}</template>\n  </category>\n"


def dump(interactions: list[dict], corpus: Path, *, dry_run: bool = False) -> dict:
    learned_path = corpus / LEARNED_FILE
    known = existing_patterns(corpus)
    added, skipped = [], []

    for pair in interactions:
        pattern = derive_pattern(pair["task"])
        answer = str(pair["answer"] or "").strip()
        usable, reason = pattern_is_usable(pattern)
        if not usable:
            skipped.append({"pattern": pattern or "(empty)", "reason": reason})
            continue
        if pattern in known:
            skipped.append({"pattern": pattern, "reason": f"already in {known[pattern]}"})
            continue
        if NON_ANSWERS.match(answer):
            skipped.append({"pattern": pattern, "reason": "answer is a refusal or empty result"})
            continue
        if len(answer) > MAX_TEMPLATE_CHARS:
            answer = answer[:MAX_TEMPLATE_CHARS].rstrip() + " …"
        known[pattern] = LEARNED_FILE if learned_path.exists() else "(new)"
        added.append({"pattern": pattern, "answer": answer, "source": pair.get("source"),
                      "app": pair.get("app"), "model": pair.get("model")})

    if added and not dry_run:
        corpus.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if learned_path.is_file():
            existing = learned_path.read_text(encoding="utf-8", errors="replace").rstrip()
            if existing.endswith("</aiml>"):
                existing = existing[: -len("</aiml>")].rstrip()
        else:
            existing = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                f"<!-- Generated by pattern_dumper.py on {stamp}.\n"
                "     Pairs learned from LLM interactions. Append-only: a pattern that already exists\n"
                "     anywhere in this corpus is never rewritten, and every learned pair is unverified. -->\n"
                "\n<aiml>"
            )
        blocks = "".join(
            compile_category(
                entry["pattern"],
                entry["answer"],
                provenance=f"learned {stamp} from {entry.get('app') or 'terminal'}"
                           f"{'/' + str(entry['model']) if entry.get('model') else ''}; unverified",
            )
            for entry in added
        )
        # Written whole and closed, so the corpus is valid XML at every moment, not only after `check`.
        learned_path.write_text(f"{existing}\n{blocks}</aiml>\n", encoding="utf-8", newline="\n")

    return {
        "learned_file": str(learned_path),
        "added": added,
        "skipped": skipped,
        "dry_run": dry_run,
    }


def close_generated_files(corpus: Path) -> list[str]:
    """The generated file opens `<aiml>` and never closes it, because it is appended to.

    A closing tag after every append would produce `</aiml></aiml>`, so instead the file is closed on
    demand — this is what `check` and any AIML loader needs, and it is safe to call repeatedly.
    """
    path = corpus / LEARNED_FILE
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    if text.rstrip().endswith("</aiml>"):
        return []
    path.write_text(text.rstrip() + "\n</aiml>\n", encoding="utf-8", newline="\n")
    return [LEARNED_FILE]


def validate(corpus: Path) -> dict:
    """Check the corpus, separating what can be fixed here from what shipped that way.

    The ALICE set is overlapping by design — thousands of patterns appear in more than one file, and a
    loader simply lets the last one win. Reporting those as failures buries the two things that matter:
    a file that will not parse, and a learned pattern that collides with hand-written knowledge.
    """
    malformed: list[str] = []
    collisions: list[str] = []
    corpus_duplicates = 0
    seen: dict[str, str] = {}

    for file in sorted(corpus.glob("*.aiml")):
        text = file.read_text(encoding="utf-8", errors="replace")
        try:
            ElementTree.fromstring(text)
        except ElementTree.ParseError as error:
            malformed.append(f"{file.name}: not well-formed XML ({error})")
        for raw in re.findall(r"<pattern>(.*?)</pattern>", text, flags=re.DOTALL):
            key = normalize_pattern(raw)
            if not key:
                continue
            if key in seen and seen[key] != file.name:
                if LEARNED_FILE in (file.name, seen[key]):
                    collisions.append(f"{key!r} is in both {seen[key]} and {file.name}")
                else:
                    corpus_duplicates += 1
            seen.setdefault(key, file.name)

    return {"malformed": malformed, "collisions": collisions, "corpus_duplicates": corpus_duplicates, "patterns": len(seen)}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Compile prompt/response interactions into AIML categories.")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS), help="ALICE corpus directory")
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR), help="Interaction log directory (also reads the terminal transcripts)")
    sub = parser.add_subparsers(dest="command", required=True)

    dump_cmd = sub.add_parser("dump", help="Append new categories for interactions not already known")
    dump_cmd.add_argument("--dry-run", action="store_true", help="Report what would be added")
    dump_cmd.add_argument("--pair", nargs=2, metavar=("PROMPT", "RESPONSE"), help="Compile one pair instead of the logs")
    dump_cmd.add_argument("--dir", action="append", default=[], help="Extra log directory to read")
    dump_cmd.add_argument("--max-words", type=int, default=MAX_WORDS, help="Longest pattern to accept")

    sub.add_parser("list", help="List the patterns already learned")
    sub.add_parser("check", help="Validate the corpus and report duplicate patterns")

    args = parser.parse_args(argv)
    if getattr(args, "max_words", None):
        globals()["MAX_WORDS"] = int(args.max_words)
    corpus = Path(args.corpus)

    if args.command == "list":
        path = corpus / LEARNED_FILE
        if not path.is_file():
            print(f"nothing learned yet ({path} does not exist)")
            return 0
        patterns = [normalize_pattern(raw) for raw in re.findall(r"<pattern>(.*?)</pattern>", path.read_text(encoding="utf-8", errors="replace"), flags=re.DOTALL)]
        for pattern in patterns:
            print(pattern)
        print(f"\n{len(patterns)} learned pattern(s) in {path.name}")
        return 0

    if args.command == "check":
        closed = close_generated_files(corpus)
        for name in closed:
            print(f"repaired {name} (missing closing tag)")
        report = validate(corpus)
        for name in report["malformed"]:
            print(f"malformed: {name}")
        for collision in report["collisions"]:
            print(f"collision: {collision}")
        files = len(list(corpus.glob("*.aiml")))
        print(f"\n{files} file(s), {report['patterns']} distinct pattern(s)")
        print(f"malformed {len(report['malformed'])}, learned collisions {len(report['collisions'])}, "
              f"pre-existing corpus overlaps {report['corpus_duplicates']} (ALICE ships overlapping sets)")
        return 0 if not report["malformed"] and not report["collisions"] else 1

    interactions = (
        [{"task": args.pair[0], "answer": args.pair[1], "source": "(command line)"}]
        if args.pair
        else interactions_from_logs(*interaction_dirs([args.log_dir] + args.dir))
    )
    if not interactions:
        print(f"no interactions found in {args.log_dir}; run a task with the terminal first", file=sys.stderr)
        return 1

    close_generated_files(corpus)
    result = dump(interactions, corpus, dry_run=args.dry_run)
    for entry in result["added"]:
        print(f"+ {entry['pattern']}")
    for entry in result["skipped"]:
        print(f"- {entry['pattern']}: {entry['reason']}")
    verb = "would add" if args.dry_run else "added"
    print(f"\n{verb} {len(result['added'])}, skipped {len(result['skipped'])} -> {result['learned_file']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
