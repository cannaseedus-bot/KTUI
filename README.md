# KTUI

A local-first terminal assistant. A Textual TUI (`chat_app.py`) and a sandboxed headless terminal
(`task-engine.py`) share one config, one model table and one set of tools. Weights are served by
`llama-server` from `runtime/llama/`; cloud models are optional advisors, never the default.

The point is that the cheap, deterministic questions never reach a model:

```
what changed        →  TOOL git status        →  On branch main …
what is the time    →  TOOL time              →  It's 5:13 PM.
convert 25 celsius… →  TOOL convert 25 C F    →  25°C is 77°F
```

```
         ▀▀▀▀
     ▄▀▀▀▀▀▀▀▀▀▀▄
    ▄▀▀▀▀▀▀▀▀▀▀▀▀▄
   ▄▀▀▀        ▀▀▀▄
  ▀▀▀▀    ▀▀    ▀▀▀▀
 ▀▀▀      ▀▀      ▀▀▀
  ▀▀▀▄    ▀▀    ▄▀▀▀
   ▀▀▀▄        ▄▀▀▀
    ▀▀▀▄▄▄▄▄▄▄▄▀▀▀
     ▀▀▀▀▀▀▀▀▀▀▀▀
```

```
workspace  ~/.<project-name>
model      read-only   `/workspace` picks a folder, `/allow` grants write+patch
session    20261123T001407-6b28b2
```


## Quick start

Windows, Python 3.11+, git, and the `.gguf` weights in `~/.models` (see `model_dir` in
`gpt-oss.toml`).

```bat
start.bat
start.bat qwen3-4b
start.bat pick
start.bat default
start.bat keys
start.bat advisor
start.bat stop
```

- `start.bat` serves `default_model`, waits for `/health`, then opens the chat app. A server already
  answering on the endpoint is reused rather than duplicated.
- `start.bat <alias>` serves another entry from `[models]` (`python task-engine.py models` lists
  them fastest first).
- `pick` shows the numbered list and serves one for this run only; `default [alias]` shows the same
  list and remembers the choice in `gpt-oss.toml`.
- `keys` prints the key page for each provider; `advisor` saves a cloud token to `.env`.
- `stop` kills the llama-server the launcher left running.

By hand:

```bat
python task-engine.py models
python task-engine.py launch --model gpt-oss-20b --keep-alive
python chat_app.py
```

`models` prints the speed dial (tier, size, present/missing) and marks the default; `launch` starts
the server and keeps it up until Ctrl+C; `chat_app.py` is the TUI. `python task-engine.py status`
reports the runtime, the model and whether the server is answering.

## Layout

| File | Role |
|---|---|
| `chat_app.py` | The TUI: header, chat, task panel, command palette, sandbox tools |
| `task-engine.py` | Headless sandboxed terminal; also `models`, `default`, `prepare`, `launch`, `tasks` |
| `gpt-oss.toml` | The only config: server, `[models]`, `[sandbox]`, `model_dir` |
| `_override.aiml` | The tool bridge — patterns that answer with `TOOL <verb>` or `__LLM_FALLBACK__` |
| `model_config.py` | Edits `default_model` in `gpt-oss.toml` without disturbing the rest of the file |
| `session_log.py` | One JSONL transcript per session (resume, rewind, search) |
| `svg_logo.py`, `logo.svg` | Allowlisted-subset SVG → half-block rasteriser, and the mark |
| `task_list.py` | The `task-list.json` bus and its AIML command bank |
| `interaction_log.py` | Prompt/answer pairs, mined into AIML by `pattern_dumper.py` |
| `start.bat` | Launcher: model choice, advisor tokens, health wait, then the app |
| `aiml-en-us-foundation-alice/` | Vendored ALICE corpus (data, LF, not edited) |

## The speed dial

`[models]` is ordered fastest first and every surface reads it top to bottom:

| Alias | Tier | Size | Use it for |
|---|---|---|---|
| `gemma-3-1b` | fastest | 0.67 GB | routing, one-line replies |
| `lfm2.5-1.2b` | fast | 1.16 GB | terse chat, tiny footprint |
| `qwen3-1.7b-q4` | fast | 1.19 GB | Qwen3 quality at 4-bit |
| `qwen3-1.7b` | balanced | 2.02 GB | better wording, same size class |
| `qwen3-4b` | strong | 3.99 GB | tool calling, multi-step tasks |
| `gpt-oss-20b` | deep | 11.28 GB | the default when it matters |

Tier is derived from the file size, so a new model gets a label automatically. The default lives in
`[server] default_model` and can be changed from the app (`/default qwen3-4b`), the launcher
(`start.bat default qwen3-4b`) or the CLI (`python task-engine.py default qwen3-4b`).

## In-app commands

Typed with a leading `/`, or picked from `Ctrl+P`:

| Command | Does |
|---|---|
| `/models` | The table above, marked with the default and what the server is actually serving |
| `/model <alias>` | Points this conversation at one alias; warns when the server is serving another |
| `/default [alias]` | Writes `default_model` to `gpt-oss.toml` (bare form uses the current model) |
| `/workspace [path]` | Opens the folder picker, or sets the workspace directly |
| `/allow`, `/allow off` | Grants or revokes write+patch for the current workspace |
| `/sessions` | Recent transcripts, `*` on the current one |
| `/resume [n\|id]`, `/rewind [n]`, `/new` | Load a transcript, drop the last exchanges, start fresh |
| `/keys` | Where each API key comes from, with links |
| `/advisor openai\|deepseek\|anthropic`, `/local` | Switch the advisor, or come back to the local server |
| `/clear` | Drop the conversation (history stays on disk) |

## AIML answers first

`_override.aiml` is the semantic layer. A template replies with either a command the app executes or
an explicit fallback:

```
TOOL <verb> <args>     run it locally (git, time, convert, files) and print the output
__LLM_FALLBACK__       nothing local knows this — hand the turn to the model
```

`<srai>` keeps one canonical phrasing per tool, so `show the diff` and `git diff` cannot drift.
Adding a tool is data, not code: add a `<category>` whose template says `TOOL git log --oneline -10`
(or extend `run_tool_verb` with a new verb). The patterns live in `_override.aiml`:
git status/diff/log/branch/ls-files/show, time, Celsius ↔ Fahrenheit, file listing, jokes.

Weather and translation deliberately return `__LLM_FALLBACK__` — they need the network or a real
model, so the app hands them over instead of inventing output.

## Workspace and permissions

The model reads inside the workspace and nothing outside it. Writes are a separate, explicit grant:

- `/workspace` opens a folder picker (`Enter` expands, `a` takes the highlighted folder, `Esc`
  cancels); `/workspace <path>` skips it.
- New workspaces are **read-only**. `/allow` makes the current one read-write; `/allow off` revokes
  it, and choosing a different folder always resets to read-only.
- `write_file` and `patch_file` are only offered to the model while the grant is on, so it is never
  shown a tool that could only refuse.
- Paths are resolved and must stay under the workspace root. `.git`, `logs`, `node_modules`, `dist`
  and `.env*` stay blocked for reads and writes alike. Writes are capped at 200 KB; a patch that
  matches nothing, or matches more than once without `replace_all`, is refused.

The model gets a written brief with the workspace path, the permission mode and every tool with the
phrasing it answers; it is refreshed when `/workspace` or `/allow` changes. A model cannot call what
it cannot name.

## Sessions

Every conversation is a file: `logs/sessions/<id>.jsonl`, append-only while live and rewritten from
memory on rewind or resume, so a torn line cannot desynchronise the app from the disk. `/sessions`
lists them, `/resume` loads one back, `/rewind [n]` drops the last exchanges (from memory *and* the
file), `/new` starts a different one. The model has a read-only `search_history` tool so it can look
up an earlier answer instead of asking again.

## Advisors (cloud, optional)

Local models need no key and no network. If you want a second opinion, `/advisor openai`,
`/advisor deepseek` or `/advisor anthropic` route the conversation to a hosted model; `/local`
comes back. Tokens live in `.env` (gitignored, and on the sandbox blocklist) and can be written by
`start.bat advisor`, which types them hidden and never puts them in a command line.

| Provider | Key page | Env var |
|---|---|---|
| OpenAI | https://platform.openai.com/api-keys | `OPENAI_API_KEY` |
| DeepSeek | https://platform.deepseek.com/api_keys | `DEEPSEEK_API_KEY` |
| Anthropic | https://platform.claude.com/settings/keys | `ANTHROPIC_API_KEY` |
| Ollama | https://ollama.com/download | none (local daemon) |

An advisor with no token is refused with the link, and the local server keeps answering.

## The sandbox

There is no shell. `run_command` takes a program name plus an argument list, the program must be on
the allowlist, **its subcommand must be on the per-program list**, and it runs with `shell=False`
inside the workspace. `git` is the interesting case:

```
status  diff  log  show  ls-files  branch  grep  describe  rev-parse
```

Anything else — `git push`, `git commit`, `git config` — is refused with the list. `python` is
limited to `-c/-m/-V` and `node` to `-e/-v/-p` (both also accept `--version`). Nothing reaches the
network, and the child process gets no environment beyond `PATH`.

## Logs

All under `logs/` (gitignored):

| Directory | What |
|---|---|
| `sessions/` | Conversation transcripts (`/resume`, `/rewind`, `search_history`) |
| `gpt-oss-terminal/` | One JSONL per terminal task |
| `llm-interactions/` | Prompt/answer pairs from every local client |
| `llama-server/` | Server stdout/stderr per launch |

`pattern_dumper.py` reads the interaction logs and compiles new pairs into AIML categories (`dump`,
`list`, `check`), which is how the learned bank grows.

## Configuration

`gpt-oss.toml` is the single source of truth:

- `[server]` — endpoint, `executable` (relative to this file), `default_model`, context, threads,
  `server_args` (`--jinja` enables native tool calling)
- `model_dir` (top level) — where the `.gguf` files live
- `[models]` — alias → filename, ordered fastest first
- `[sandbox]` — `root` (`"."` is this repo), `allow_write`, `allow_network`, step and size caps,
  `blocked` paths

The terminal's flags can lower these ceilings (`--root`, `--allow-write`, `--max-steps`,
`--max-tokens`, `--context`, `--executable`); they cannot raise them above the file.

## Checking it works

There is no test suite yet — that is the honest gap. The paths exercised by hand so far:

```bat
python task-engine.py models
python task-engine.py status
python task-engine.py launch --model gemma-3-1b --task "reply ready"
start.bat gemma-3-1b
```

`models` renders the table and marks the default; `status` reports the runtime, the model file and
the server; `launch --task` starts the server, runs one task and stops it; `start.bat` brings the
whole stack up and waits for `/health`.

Inside the app: `/models`, `/keys`, `what changed`, `/workspace`, `/allow`, `/sessions`, `/resume`,
`/rewind`. The SVG allowlist refuses `<script>`, event handlers, image references, entities and
relative path commands (`svg_logo.UnsafeSVG`).

## What this does not do

- **No remote.** `git push` has nowhere to go until one is configured; recovery is local-only.
- **No network for the sandbox.** Search, weather and translation are the model's job, not a tool's.
- **One model per server.** `llama-server` serves what it was launched with; `/model` changes which
  id the app asks for, not what is loaded — the app says so when they disagree.
- **Windows launcher.** `start.bat` is cmd/PowerShell; the Python parts are portable.

## Requirements

Python 3.11+ (`tomllib`), `textual` 8.x, `openai`, `pydantic` 2, `python-aiml`, `requests`,
`beautifulsoup4`, and a `llama-server` build in `runtime/llama/` (the server-only subset of the
llama-haswell package; `python task-engine.py prepare` stages it from `node_modules`).
