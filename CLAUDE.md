# CLAUDE.md

<!-- Claude Code auto-loads this file at session start.
     The SessionStart hook (hooks/session-start.py) separately injects
     knowledge/index.md and the most recent daily log as additionalContext,
     so the current knowledge base state arrives in your first <system-reminder>. -->

## What this project is

A self-compiling personal knowledge base. Raw source documents — conversation logs, web clippings, meeting notes, anything markdown — land in buckets under `raw/`. `scripts/compile.py` promotes those sources into structured, cross-referenced articles under `knowledge/`. Future sessions start with the knowledge index pre-injected so you can answer questions against accumulated context instead of re-deriving from scratch.

Full design reference: `AGENTS.md`. Pattern background: `llm-wiki.md`. User-facing overview: `README.md`.

## Content models

This working directory is a **public structural repo** (scripts, hooks, docs). The three content directories — `raw/`, `knowledge/`, `notes/` — are gitignored here and can be set up in one of two ways:

- **Linked mode (recommended):** symlinks into a private content repo, conventionally a sibling like `../obsidian-brain-content/`. Symlinks are *relative*, so the pair can relocate together. Gives version history + backup + cross-machine sync.
- **Solo mode:** real directories inside this checkout. Content stays local, gitignored. No second repo; simpler, but no off-site backup.

Either way, scripts and hooks operate through the paths transparently — path construction is lexical (`ROOT_DIR / "raw"`), so `relative_to(ROOT_DIR)` still produces stable keys like `raw/daily/2026-04-10.md` in `state.json` regardless of mode.

Don't hardcode any absolute paths in docs, scripts, or generated content — users clone this repo to arbitrary locations. Refer to the structural repo's working directory as "this repo", and the content repo by its conventional relative path (`../obsidian-brain-content`) or with a placeholder like `<content-repo>/`.

Implications for agent work:

- **Commits split by layer (linked mode).** Structural changes (scripts, hooks, docs, `.claude/`, `justfile`, `.gitignore`) commit to *this* repo. Content changes (`raw/**`, `knowledge/**`, `notes/**`) commit to the content repo — `cd "$(readlink raw)/.."` reaches it. **In solo mode** there is no second repo: content simply isn't tracked (or the user tracks it on their own).
- **`.gitignore` patterns use no trailing slashes.** `raw`, `knowledge`, `notes` match both symlink blobs (linked mode) and real directories with contents (solo mode). A trailing slash (`raw/`) would restrict the match to directories only, which would *not* catch symlinks. Don't add trailing slashes back, and don't split into separate patterns for the two modes — one pattern covers both.
- **Setup.** `just setup-content` (interactive prompt), `just solo` (solo mode), `just init-content <path>` (new linked), `just link-content <path>` (existing linked). All go through `scripts/link-content.py`; idempotent, refuses to silently cross-switch modes.
- **A broken symlink** (content repo path moved or deleted) makes scripts fail on file I/O. `ls -la raw` is the first diagnostic for "file not found" errors.

## Directory contract

Paths under `raw/`, `knowledge/`, and `notes/` are gitignored here and resolve either through symlinks into a content repo (linked mode) or to real directories in this checkout (solo mode). See "Content models" above. Writes to those paths don't land in this repo either way — in linked mode they land in the content repo (commit there); in solo mode they stay local.

| Path | Owner | Rule |
|------|-------|------|
| `raw/` `knowledge/` `notes/` | symlinks *or* real dirs | Gitignored here. Set up by `scripts/link-content.py` in either mode. |
| `notes/*.md` | Human | Freeform scratch space. Outside `RAW_DIR`; not scanned by `list_raw_files()` and never enters the compile/query/lint pipeline. Use for working drafts that shouldn't become compiled knowledge. |
| `raw/daily/YYYY-MM-DD.md` | Human + `flush.py` | Conversation logs. Append only. Hashed by `scripts/state.json`. The SessionStart hook auto-injects today's file into the next session. |
| `raw/clippings/*.md` | Obsidian Web Clipper + human | Web article captures. Same immutability + compile rules. Not auto-injected. |
| `raw/research/*.md` | Human | Research notes, papers, long-form investigation. Treated as a standard source bucket by compile. |
| `raw/<new-bucket>/*.md` | Whoever creates the bucket | Any immediate subdir of `raw/` is auto-discovered by `list_raw_files()` in `scripts/utils.py`. Adding a new source type is `mkdir raw/<name>` — no code changes needed. |
| `raw/*/assets/` | Human + external tools | Image/binary attachments. Skipped during markdown discovery (`_RAW_SKIP_DIRS` in `scripts/utils.py`). LFS-tracked in the content repo when set up per README. |
| `knowledge/concepts/` | `compile.py` sub-agent | LLM-owned. Do not hand-write articles here during interactive sessions. |
| `knowledge/connections/` | `compile.py` sub-agent | Same — LLM-owned. |
| `knowledge/qa/` | `query.py --file-back` sub-agent | Same — LLM-owned. |
| `knowledge/index.md` | Compile/query sub-agents | Master catalog. Injected into every session. Sub-agents update it. |
| `knowledge/log.md` | Compile/query sub-agents | Append-only build log. |
| `scripts/*.py` | Human | Source. Edit freely. |
| `scripts/state.json` | Scripts | Compile cache. Keys are paths relative to repo root (e.g. `raw/daily/2026-04-10.md`). Never hand-edit. |
| `scripts/last-flush.json`, `scripts/flush.log` | Scripts | Runtime artifacts. Ignore. |
| `hooks/*.py` | Human | Edit carefully — changes affect every session. Timeouts from `.claude/settings.json`: SessionStart 15s, PreCompact 10s, SessionEnd 10s. Hooks make no LLM/API calls (only local I/O + subprocess spawns); the heavy work happens in the detached `flush.py`. |
| `reports/` | `lint.py` | Generated lint reports. |

## Workflow invariants

1. **`raw/` is source code. `knowledge/` is the executable.** Never hand-write concept articles in an interactive session. If you want knowledge saved, put it in the appropriate `raw/` bucket and let the compile pipeline promote it.
2. **Hand-editing a raw source after compilation invalidates its hash.** `lint.py` will flag it as stale. Fix by running `uv run python scripts/compile.py` to recompile the changed file.
3. **Before answering a question that might already be covered, consult the injected index first.** If an `[[concepts/…]]` entry looks relevant, `Read` it instead of re-deriving. Cite sources using `[[path/slug]]` wikilinks (no `.md` extension).
4. **Prefer `scripts/query.py` over manual synthesis** when the user's question spans multiple articles. Use `--file-back` when the answer itself is worth preserving.
5. **Never delete a raw source that has been compiled.** Compiled articles reference it in their `sources:` frontmatter (e.g. `raw/daily/2026-04-10.md`); deletion creates broken links.
6. **The `CLAUDE_INVOKED_BY` env var is load-bearing.** Set at the top of `flush.py`, `compile.py`, and `query.py` before the Agent SDK is invoked. Honored by all three hooks (`session-start.py`, `session-end.py`, `pre-compact.py`), which exit immediately when it's present. Together, these prevent the hooks from firing inside the SDK's bundled Claude Code subprocess — which would otherwise cause recursion, overhead, and (as of the fix on 2026-04-18) spurious `Command failed with exit code 1` errors after each compile/query/flush.

## Adding raw sources manually

This is a bring-your-own-markdown system. You do not need Claude to capture knowledge. (Note: this section is about adding files into the `raw/` buckets that feed the compile pipeline — not to be confused with the `notes/` directory, which is freeform scratch outside the pipeline.)

- **For day-of notes** (meetings, decisions, quick observations): append a new section to `raw/daily/YYYY-MM-DD.md`. It rides the same compile pipeline as auto-flushed session summaries and gets auto-injected into tomorrow's session.
- **For topic-spanning notes** (book chapters, multi-day investigation, meeting series): drop the file into an existing bucket — `raw/research/` for long-form investigation, `raw/clippings/` for web captures — or create a new bucket with `mkdir raw/<name>` and add files there. Compile auto-discovers every bucket; only the SessionStart auto-injection is skipped for non-daily files (compiled articles reach future sessions via the index one step later).
- **Images and attachments** go in a sibling `assets/` subdirectory of the bucket (e.g. `raw/clippings/assets/`). These are skipped during markdown discovery. Set Obsidian's attachment folder to match.

## Key commands

All commands are wrapped as `just` recipes (see `justfile`). Run `just` to list them. The raw `uv run …` form still works if you need to bypass the wrapper.

```bash
just compile                 # compile new/changed daily logs
just compile-all             # force full recompile
just compile-dry             # preview
just ask "question"          # ask the knowledge base
just ask-save "question"     # ask + save answer to knowledge/qa/
just lint                    # all health checks
just lint-structural         # skip LLM contradiction check (free)
just flush                   # manually flush a session transcript
just collect-assets          # move stray root images into raw/clippings/assets/
just setup-content           # interactive: pick solo or linked content model
just solo                    # solo mode (non-interactive): real dirs in this checkout
just init-content <path>     # linked mode: create skeleton content repo at <path> + symlink
just link-content <path>     # linked mode: symlink an existing content repo at <path>
```

First-time setup: `./scripts/setup.sh` installs `just`, `uv`, and Python deps (idempotent). Then `just setup-content` to choose and wire up the content model. See `README.md` for the full walkthrough.

Each `just` recipe also has a matching slash command in `.claude/commands/<name>.md` and a matching agent skill in `.claude/skills/kb-<name>/` — so inside Claude Code you can invoke them as `/compile`, `/ask`, `/lint`, `/flush`, `/setup`, etc. The command/skill files are thin wrappers over the `just` recipes; modify the recipe in `justfile`, the wrappers stay valid.

## Triggering a flush mid-session

- `/compact` fires the PreCompact hook, which spawns `flush.py` in the background while the session continues. Use this to capture a chunk of work without exiting.
- `/exit` fires SessionEnd, which also spawns `flush.py`. Use this when done.
- Both paths dedup on `session_id` within 60 seconds — firing both is safe.

## When to read AGENTS.md

Read `AGENTS.md` in full when you need to:
- Create or modify a knowledge article (it defines YAML frontmatter + section schema).
- Change hook behavior or understand the cross-platform specifics.
- Understand the exact prompts used by `compile.py`, `query.py`, or `lint.py`.

For routine Q&A and in-session work, the injected index is usually enough.

## Infrastructure notes

- The scripts invoke Claude under the hood via `claude_agent_sdk`, which spawns a bundled Claude Code CLI subprocess. Billing is against your Claude subscription, not API credits.
- Sub-agents in `compile.py` / `query.py --file-back` run with `permission_mode="acceptEdits"` and `allowed_tools=["Read","Write","Edit","Glob","Grep"]` — they write files directly without prompting.
- Running a manual flush while the parent Claude Code session is still alive can race the bundled CLI subprocess. Prefer `/compact` or `/exit` over manually piping JSON into `hooks/session-end.py`.
