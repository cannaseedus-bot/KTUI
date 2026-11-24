"""The knowledge banks the daemon learns, in one place, so the projection and the kernel agree.

The ALICE foundation corpus in this checkout is 84 files and ~99,900 categories, but `startup.xml` -
the file that would load them - is not in the tarball, so the host used to learn only the learned bank.
That is why "what is Saturn" went to the model: the knowledge was on disk, never in the kernel.

This list is the curated subset that answers knowledge questions without swallowing the conversation:

- **no catch-all banks.** `default.aiml`, `ai.aiml`, `alice.aiml` and `badanswer.aiml` are excluded,
  because their `<pattern>*</pattern>` style categories would answer everything - which would break
  the honest "no local answer, deferring to the model" path and the multi-intent routing.
- **bounded.** 25 banks, ~11,000 categories, about 0.4 seconds to learn.
- **loaded before the host's own banks**, so the daemon's greetings, identity, memory and git
  operations always win over a generic corpus answer.

`KNUMATIC_KNOWLEDGE=off` disables the whole set for a session.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
ALICE_DIR = APP_ROOT / "aiml-en-us-foundation-alice"
FILES = (
    "knowledge", "geography", "atomic", "biography", "computers", "humor", "movies", "music",
    "numbers", "religion", "science", "sports", "history", "food", "money", "literature",
    "personality", "emotion", "inquiry", "primitive-math", "wallace",
)
# Named so each exclusion is a decision in code, not an omission someone has to guess at. The first
# four are catch-all banks: their broad patterns answer every sentence, which breaks the honest
# "no local answer" path. The last four are prose/context banks that answer sentences they have no
# business answering - measured: "hey, how are you, and can you check my server?" came back as
# "All of them?" from that.aiml and "I think there might be a few exceptions." from update1.aiml.
EXCLUDED = ("default", "ai", "alice", "badanswer", "that", "update1", "stories", "salutations")


def enabled() -> bool:
    return os.environ.get("KNUMATIC_KNOWLEDGE", "").strip().lower() not in {"off", "0", "no", "false"}


def paths() -> list[Path]:
    """The knowledge banks that exist on this checkout, in load order."""
    if not enabled():
        return []
    return [ALICE_DIR / f"{name}.aiml" for name in FILES if (ALICE_DIR / f"{name}.aiml").is_file()]


def summary() -> dict:
    found = paths()
    return dict(enabled=enabled(), files=len(found), excluded=list(EXCLUDED),
                missing=[name for name in FILES if not (ALICE_DIR / f"{name}.aiml").is_file()])
