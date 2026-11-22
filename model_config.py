"""Edit gpt-oss.toml's default model without disturbing the rest of the file.

Three callers offer the same thing - `task-engine.py default`, start.bat's menu and the chat app's
/default and palette entries - and each would otherwise grow its own regex over the same two lines.
gpt-oss.toml is a hand-written document, so the edit is deliberately surgical: only the matched
alias changes, and comments, ordering and spacing survive byte for byte.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "gpt-oss.toml"

# The one line that matters, with whatever inline comment already follows it left alone.
DEFAULT_LINE = re.compile(
    r'^(?P<head>[ \t]*default_model[ \t]*=[ \t]*")(?P<alias>[^"]*)(?P<tail>".*)$',
    re.MULTILINE,
)


def read(path: Path = CONFIG_PATH) -> dict:
    """The parsed file, or {} when it is missing or unreadable."""
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, ValueError):
        return {}


def registry(path: Path = CONFIG_PATH) -> dict[str, str]:
    """Alias -> filename in file order: fastest first, deepest last."""
    models = read(path).get("models") or {}
    return {str(alias): str(target) for alias, target in models.items() if str(alias).strip()}


def default_model(path: Path = CONFIG_PATH) -> str:
    return str((read(path).get("server") or {}).get("default_model") or "")


def set_default_model(alias: str, path: Path = CONFIG_PATH) -> str:
    """Persist `[server] default_model = alias`. Returns the alias, raises ValueError otherwise."""
    alias = (alias or "").strip().strip('"')
    known = registry(path)
    if not known:
        raise ValueError(f"no [models] table in {path}")
    if alias not in known:
        raise ValueError(f"unknown alias '{alias}'; known: {', '.join(known)}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"cannot read {path}: {error}") from error
    updated, replacements = DEFAULT_LINE.subn(
        lambda match: f"{match.group('head')}{alias}{match.group('tail')}", text, count=1
    )
    if not replacements:
        raise ValueError(f"{path} has no default_model line to edit")
    path.write_text(updated, encoding="utf-8", newline="\n")
    return alias
