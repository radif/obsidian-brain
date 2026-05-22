# AGENTS.md - Personal Knowledge Base Schema

> Adapted from [Andrej Karpathy's LLM Knowledge Base](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) architecture.
> Instead of ingesting external articles, this system compiles knowledge from your own AI conversations.

## The Compiler Analogy

```
raw/            = source code    (conversations, clippings, notes - the raw material)
LLM             = compiler       (extracts and organizes knowledge)
knowledge/      = executable     (structured, queryable knowledge base)
lint            = test suite     (health checks for consistency)
queries         = runtime        (using the knowledge)
```

You don't manually organize your knowledge. Sources land in `raw/`, and the LLM handles the synthesis, cross-referencing, and maintenance.

## Content models

The structural repo (`obsidian-brain`, public) holds the tooling: scripts, hooks, `.claude/`, docs, justfile. This file.

The three content directories — `raw/`, `knowledge/`, `notes/` — are gitignored in the structural repo and can be set up in one of two ways:

- **Linked mode** (recommended): relative symlinks pointing into a private content repo (conventionally `../obsidian-brain-content/`). Gives version history, backup, and cross-machine sync.
- **Solo mode**: real directories inside the structural repo checkout. Content stays local, still gitignored so it never leaks into the public repo. Simpler, no second repo.

Either mode works with the same scripts and hooks. Path construction is lexical (`ROOT_DIR / "raw"`) and `relative_to(ROOT_DIR)` reduces lexically too, so `state.json` keys, source frontmatter, and wikilinks stay as `raw/daily/…` / `knowledge/concepts/…` regardless of where the bytes physically live.

### Why the gitignore has no trailing slashes

The structural repo's `.gitignore` lists `raw`, `knowledge`, `notes` without trailing slashes. This is deliberate: a pattern like `raw/` would only match directory trees, not symlink blobs, so linked mode would leak the symlinks into the public repo. The pattern `raw` (without slash) matches both — real directories and their contents (solo mode) *and* symlink blobs (linked mode). One pattern list supports both models; don't split it.

### Setup

`scripts/link-content.py` handles both modes — `just setup-content` (interactive), `just solo`, `just init-content <path>`, or `just link-content <path>`. See `README.md` for the walkthrough. The script refuses to silently cross-switch modes: if symlinks exist it won't accept `--solo`, and vice versa.

### `notes/` is not part of the compile pipeline

Of the three content directories, `notes/` is special: it is **outside the compile pipeline**. `list_raw_files()` (`scripts/utils.py`) walks `RAW_DIR` only, so nothing in `notes/` is ever read by `compile.py`, `query.py`, or `lint.py`. Use it for freeform scratch — working drafts, idea dumps, personal journaling — that you want in your content store but explicitly kept out of the knowledge base.

---

## Architecture

### Layer 1: `raw/` - Source Documents (Immutable)

The `raw/` directory holds every source document the compiler reads. Each
immediate subdirectory is a *bucket* — a category of source. Buckets are
auto-discovered by `list_raw_files()` in `scripts/utils.py`; adding a new
source type is `mkdir raw/<name>`, no code changes required.

```
raw/
├── daily/              # conversation logs written by flush.py
│   ├── 2026-04-01.md
│   ├── 2026-04-02.md
│   └── ...
├── clippings/          # Obsidian Web Clipper output
│   ├── AI 2027.md
│   ├── assets/         # images — not scanned for markdown
│   └── ...
├── research/           # long-form notes, papers, multi-day investigation
│   └── ...
└── <other buckets>/    # meetings/, pdfs/, etc. — whatever you add
```

Subdirectories named `assets` are skipped during markdown discovery so image
attachments can live alongside their source notes without polluting the compile
queue.

Daily conversation logs (`raw/daily/YYYY-MM-DD.md`) are the one bucket that's
produced automatically — written by `flush.py` after each session. Every other
bucket is populated by the human (or by external tools like the Obsidian Web
Clipper).

When a daily log is first touched (by `flush.py`), the file is created with this skeleton:

```markdown
# Daily Log: YYYY-MM-DD

## Sessions

## Memory Maintenance

```

Subsequent flushes append entries to the end of the file. Each entry is wrapped as `### <Section> (HH:MM)` where `<Section>` is either `Session` (real conversation extract) or `Memory Maintenance` (a `FLUSH_OK` / `FLUSH_ERROR` marker). The body of a normal Session entry uses this structure:

```markdown
### Session (HH:MM)

**Context:** What the user was working on.

**Key Exchanges:**
- User asked about X, assistant explained Y
- Decided to use Z approach because...
- Discovered that W doesn't work when...

**Decisions Made:**
- Chose library X over Y because...
- Architecture: went with pattern Z

**Lessons Learned:**
- Always do X before Y to avoid...
- The gotcha with Z is that...

**Action Items:**
- [ ] Follow up on X
- [ ] Refactor Y when time permits
```

(`flush.py:append_to_daily_log` simply appends to the end of the file rather than inserting under the right `##` heading, so in practice the two top-level section headers are cosmetic — all entries accumulate below `## Memory Maintenance`.)

### Layer 2: `knowledge/` - Compiled Knowledge (LLM-Owned)

The LLM owns this directory entirely. Humans read it but rarely edit it directly.

```
knowledge/
├── index.md              # Master catalog - every article with one-line summary
├── log.md                # Append-only chronological build log
├── concepts/             # Atomic knowledge articles
├── connections/          # Cross-cutting insights linking 2+ concepts
└── qa/                   # Filed query answers (compounding knowledge)
```

### Layer 3: This File (AGENTS.md)

The schema that tells the LLM how to compile and maintain the knowledge base. This is the "compiler specification."

---

## Structural Files

### `knowledge/index.md` - Master Catalog

A table listing every knowledge article. This is the primary retrieval mechanism - the LLM reads this FIRST when answering any query, then selects relevant articles to read in full.

Written by the runner (`scripts/compile.py`, `scripts/query.py`) from each
article's `summary:` frontmatter after the sub-agent returns successfully,
NEVER by the sub-agent itself. Sub-agents must not Read, Write, or Edit this
file. Keeping the runner as the sole writer bounds the row count by the
number of articles and bounds each Summary cell at 200 chars, which prevents
index.md from outgrowing the Claude Agent SDK's 1 MiB per-message buffer
(each sub-agent Edit echoes the post-edit file via `tool_use_result`, so
once index.md crosses ~960 KB every compile fails).

Format:

```markdown
# Knowledge Base Index

| Article | Summary | Compiled From | Updated |
|---------|---------|---------------|---------|
| [[concepts/supabase-auth]] | Row-level security patterns and JWT gotchas | raw/daily/2026-04-02.md | 2026-04-02 |
| [[connections/auth-and-webhooks]] | Token verification patterns shared across Supabase auth and Stripe webhooks | raw/daily/2026-04-02.md, raw/daily/2026-04-04.md | 2026-04-04 |
```

### `knowledge/log.md` - Build Log

Append-only chronological record of every compile and filed query. Written by
the runner (`scripts/compile.py`, `scripts/query.py`) after the sub-agent
returns successfully, NEVER by the sub-agent itself. Sub-agents must not Read,
Write, or Edit this file. Keeping the runner as the sole writer bounds the
per-entry size and prevents log.md from outgrowing the Claude Agent SDK's
1 MiB per-message buffer (each sub-agent Edit echoes the post-edit file via
`tool_use_result`, so once log.md crosses ~960 KB every compile fails).

Format (one entry per successful run):

```markdown
# Build Log

## [2026-04-01T14:30:00-07:00] compile | raw/daily/2026-04-01.md
- Created: [[concepts/nextjs-project-structure]], [[concepts/tailwind-setup]]
- Updated: [[concepts/typescript-config]]
- Cost: $0.1234

## [2026-04-02T09:00:00-07:00] query (filed) | How do I handle auth redirects?
- Filed: [[qa/auth-redirect-handling]]
- Cost: $0.0456
```

---

## Article Formats

### Concept Articles (`knowledge/concepts/`)

One article per atomic piece of knowledge. These are facts, patterns, decisions, preferences, and lessons extracted from your conversations.

```markdown
---
title: "Concept Name"
aliases: [alternate-name, abbreviation]
tags: [domain, topic]
summary: "One-line summary, ≤200 chars, neutral encyclopedic register. Used verbatim as this article's row in knowledge/index.md."
sources:
  - "raw/daily/2026-04-01.md"
  - "raw/daily/2026-04-03.md"
created: 2026-04-01
updated: 2026-04-03
---

# Concept Name

[2-4 sentence core explanation]

## Key Points

- [Bullet points, each self-contained]

## Details

[Deeper explanation, encyclopedia-style paragraphs]

## Related Concepts

- [[concepts/related-concept]] - How it connects

## Sources

- [[raw/daily/2026-04-01.md]] - Initial discovery during project setup
- [[raw/daily/2026-04-03.md]] - Updated after debugging session
```

### Connection Articles (`knowledge/connections/`)

Cross-cutting synthesis linking 2+ concepts. Created when a conversation reveals a non-obvious relationship.

```markdown
---
title: "Connection: X and Y"
connects:
  - "concepts/concept-x"
  - "concepts/concept-y"
summary: "One-line summary, ≤200 chars. Used verbatim as this article's row in knowledge/index.md."
sources:
  - "raw/daily/2026-04-04.md"
created: 2026-04-04
updated: 2026-04-04
---

# Connection: X and Y

## The Connection

[What links these concepts]

## Key Insight

[The non-obvious relationship discovered]

## Evidence

[Specific examples from conversations]

## Related Concepts

- [[concepts/concept-x]]
- [[concepts/concept-y]]
```

### Q&A Articles (`knowledge/qa/`)

Filed answers from queries. Every complex question answered by the system can be permanently stored, making future queries smarter.

```markdown
---
title: "Q: Original Question"
question: "The exact question asked"
summary: "One-line summary of the answer, ≤200 chars. Used verbatim as this article's row in knowledge/index.md."
consulted:
  - "concepts/article-1"
  - "concepts/article-2"
filed: 2026-04-05
---

# Q: Original Question

## Answer

[The synthesized answer with [[wikilinks]] to sources]

## Sources Consulted

- [[concepts/article-1]] - Relevant because...
- [[concepts/article-2]] - Provided context on...

## Follow-Up Questions

- What about edge case X?
- How does this change if Y?
```

---

## Core Operations

### 1. Compile (raw/ -> knowledge/)

When processing a raw source (conversation log, clipping, meeting notes, etc.):

1. Read the raw source file
2. Read `knowledge/index.md` to understand current knowledge state
3. Read existing articles that may need updating
4. For each piece of knowledge found in the log:
   - If an existing concept article covers this topic: UPDATE it with new information, add the daily log as a source
   - If it's a new topic: CREATE a new `concepts/` article
5. If the log reveals a non-obvious connection between 2+ existing concepts: CREATE a `connections/` article
6. Write a `summary:` field in each new or updated article's frontmatter (≤200 chars). The runner regenerates `knowledge/index.md` from these summaries after you return; do NOT modify `knowledge/index.md` or `knowledge/log.md` directly.

**Important guidelines:**
- A single daily log may touch 3-10 knowledge articles
- Prefer updating existing articles over creating near-duplicates
- Use Obsidian-style `[[wikilinks]]` with full relative paths from knowledge/
- Write in encyclopedia style - factual, concise, self-contained
- Every article must have YAML frontmatter, including a `summary:` line (≤200 chars)
- Every article must link back to its source daily logs

### 2. Query (Ask the Knowledge Base)

1. Read `knowledge/index.md` (the master catalog)
2. Based on the question, identify 3-10 relevant articles from the index
3. Read those articles in full
4. Synthesize an answer with `[[wikilink]]` citations
5. If `--file-back` is specified: create a `knowledge/qa/` article with a `summary:` frontmatter line (≤200 chars). The runner regenerates `knowledge/index.md` from the summary and appends to `knowledge/log.md` after the sub-agent returns. Do NOT modify `knowledge/index.md` or `knowledge/log.md` directly.

**Why this works without RAG:** At personal knowledge base scale (50-500 articles), the LLM reading a structured index outperforms cosine similarity. The LLM understands what the question is really asking and selects pages accordingly. Embeddings find similar words; the LLM finds relevant concepts.

### 3. Lint (Health Checks)

Seven checks, run periodically:

1. **Broken links** - `[[wikilinks]]` pointing to non-existent articles
2. **Orphan pages** - Articles with zero inbound links from other articles
3. **Orphan sources** - Daily logs that haven't been compiled yet
4. **Stale articles** - Source daily log changed since article was last compiled
5. **Contradictions** - Conflicting claims across articles (requires LLM judgment)
6. **Missing backlinks** - A links to B but B doesn't link back to A
7. **Sparse articles** - Below 200 words, likely incomplete

Output: a markdown report with severity levels (error, warning, suggestion).

---

## Conventions

- **Wikilinks:** Use Obsidian-style `[[path/to/article]]` without `.md` extension
- **Writing style:** Encyclopedia-style, factual, third-person where appropriate
- **Dates:** ISO 8601 (YYYY-MM-DD for dates, full ISO for timestamps in log.md)
- **File naming:** lowercase, hyphens for spaces (e.g., `supabase-row-level-security.md`)
- **Frontmatter:** Every article must have YAML frontmatter with at minimum: title, summary (≤200 chars), sources, created, updated
- **Sources:** Always link back to the daily log(s) that contributed to an article

---

## Full Project Structure

The structural repo (public) holds the tooling. Content lives either inside this repo (solo mode) or in a separate private repo surfaced via symlinks (linked mode). Combined view:

```
obsidian-brain/                      # Structural repo (public, this repo)
|-- .claude/
|   |-- settings.json                # Hook configuration (auto-activates in Claude Code)
|   |-- commands/ skills/            # Slash commands + agent skills
|-- .gitignore                       # Ignores raw/knowledge/notes (symlinks OR real dirs)
|-- AGENTS.md                        # This file - schema + full technical reference
|-- CLAUDE.md                        # Project instructions auto-loaded by Claude Code
|-- README.md                        # Setup walkthrough + overview
|-- justfile                         # Wrapped CLI (just --list)
|-- pyproject.toml                   # Python deps (at root so hooks can find it)
|-- scripts/                         # CLI tools
|   |-- link-content.py              #   Content setup (linked or solo mode)
|   |-- compile.py                   #   Compile raw sources -> knowledge articles
|   |-- query.py                     #   Ask questions (index-guided, no RAG)
|   |-- lint.py                      #   7 health checks
|   |-- flush.py                     #   Extract memories from conversations (background)
|   |-- config.py                    #   Path constants
|   |-- utils.py                     #   Shared helpers
|-- hooks/                           # Claude Code hooks
|   |-- session-start.py             #   Injects knowledge into every session
|   |-- session-end.py               #   Extracts conversation -> daily log
|   |-- pre-compact.py               #   Safety net: captures context before compaction
|-- reports/                         # Lint reports (gitignored)
|
|-- raw                              # linked: -> ../obsidian-brain-content/raw
|                                    # solo:   real directory with daily/, clippings/, …
|-- knowledge                        # linked: -> ../obsidian-brain-content/knowledge
|                                    # solo:   real directory with concepts/, connections/, qa/
|-- notes                            # linked: -> ../obsidian-brain-content/notes
                                     # solo:   real directory
```

In linked mode, the content repo (private, per user) looks like:

```
obsidian-brain-content/              # Content repo (private, per user)
|-- .gitignore                       # Excludes reconstructible reference material
|-- .gitattributes                   # LFS patterns (*.pdf, *.png, *.jpg, ...)
|-- raw/                             # "Source code" - immutable source documents
|   |-- daily/                       #   Conversation logs written by flush.py
|   |-- clippings/                   #   Obsidian Web Clipper output
|   |-- research/                    #   Long-form notes, papers, investigation
|   |-- <other buckets>/             #   Any subdir is auto-discovered by compile
|-- knowledge/                       # "Executable" - compiled knowledge (LLM-owned)
|   |-- index.md                     #   Master catalog - THE retrieval mechanism
|   |-- log.md                       #   Append-only build log
|   |-- concepts/                    #   Atomic knowledge articles
|   |-- connections/                 #   Cross-cutting insights linking 2+ concepts
|   |-- qa/                          #   Filed query answers (compounding knowledge)
|-- notes/                           # Freeform scratch — OUTSIDE the compile pipeline
```

In solo mode, that second tree is simply moved into the structural repo working directory as real subdirectories, still gitignored.

---

## Hook System (Automatic Capture)

Hooks are configured in `.claude/settings.json` and fire automatically when you use Claude Code in this project.

### `.claude/settings.json` Format

```json
{
  "hooks": {
    "SessionStart": [{ "matcher": "", "hooks": [{ "type": "command", "command": "uv run python hooks/session-start.py", "timeout": 15 }] }],
    "PreCompact": [{ "matcher": "", "hooks": [{ "type": "command", "command": "uv run python hooks/pre-compact.py", "timeout": 10 }] }],
    "SessionEnd": [{ "matcher": "", "hooks": [{ "type": "command", "command": "uv run python hooks/session-end.py", "timeout": 10 }] }]
  }
}
```

Commands use simple relative paths from the project root. Empty `matcher` catches all events.

### Hook Details

**`session-start.py`** (SessionStart, 15s timeout in `.claude/settings.json`)
- Recursion guard: exits immediately with no output if `CLAUDE_INVOKED_BY` is set (i.e. when invoked by the Claude Code subprocess that the Agent SDK spawns from `flush.py`, `compile.py`, or `query.py`). Without this guard, the SDK subprocess fires this hook, which runs collect-assets and injects 20 KB of context — overhead that also destabilizes the SDK session and produces the spurious "Command failed with exit code 1" errors observed pre-fix.
- No LLM calls. Local file I/O plus one subprocess spawn (collect-assets, 5s timeout).
- Builds the injected context from three parts: today's calendar date, `knowledge/index.md`, and the most recent daily log (today's, or yesterday's if today's doesn't exist).
- The daily log is truncated to its last `MAX_LOG_LINES = 30` lines before injection.
- Total context capped at `MAX_CONTEXT_CHARS = 20_000`; anything longer is truncated with a `...(truncated)` marker.
- Side effect: shells out to `scripts/collect-assets.py` to sweep any stray root-level images into `raw/clippings/assets/` (Obsidian Web Clipper drops attachments at the repo root when its settings aren't configured). Output is swallowed; failures are ignored so the hook never blocks the session.
- Outputs JSON to stdout: `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}`.

**`session-end.py`** (SessionEnd)
- Reads hook input from stdin (JSON with `session_id`, `transcript_path`, `cwd`)
- Copies the raw JSONL transcript to a temp file (no parsing in the hook - keeps it fast)
- Spawns `flush.py` as a fully detached background process
- Recursion guard: exits immediately if `CLAUDE_INVOKED_BY` env var is set

**`pre-compact.py`** (PreCompact, 10s timeout)
- Same architecture as session-end.py (parse stdin, extract last 30 turns, spawn `flush.py`), but with a stricter filter: `MIN_TURNS_TO_FLUSH = 5`. Short interactions (under 5 turns) don't fire a flush. SessionEnd uses `MIN_TURNS_TO_FLUSH = 1`, so it always flushes non-empty sessions.
- Fires before Claude Code auto-compacts the context window.
- Guards against empty `transcript_path` (known Claude Code bug #13668).
- Critical for long sessions: captures context before summarization discards it.

**Why both PreCompact and SessionEnd?** Long-running sessions may trigger multiple auto-compactions before you close the session. Without PreCompact, intermediate context is lost to summarization before SessionEnd ever fires.

### Slash Commands and Agent Skills

Beyond the three hooks, the project ships two more Claude Code integration surfaces — both live under `.claude/`:

- **`.claude/commands/<name>.md`** — slash commands. Each file registers a `/<name>` invocation that runs the matching `just` recipe. Present: `/ask`, `/ask-save`, `/compile`, `/compile-all`, `/compile-dry`, `/collect-assets`, `/collect-assets-dry`, `/flush`, `/lint`, `/lint-structural`, `/setup`.
- **`.claude/skills/kb-<name>/`** — agent skills. Each skill is a directory containing a `SKILL.md` that tells a spawned sub-agent how to use the corresponding recipe. Present: `kb-ask`, `kb-ask-save`, `kb-compile`, `kb-compile-all`, `kb-compile-dry`, `kb-collect-assets`, `kb-collect-assets-dry`, `kb-flush`, `kb-lint`, `kb-lint-structural`, `kb-setup`.

Both are thin wrappers over the `justfile` recipes: if you change a recipe's behavior, the wrappers pick it up automatically. When adding a new recipe, mirror it into both `.claude/commands/` and `.claude/skills/` for parity.

### Background Flush Process (`flush.py`)

Spawned as a subprocess with `stdout` / `stderr` → `DEVNULL`, by either hook. The spawn uses **different flags than an earlier iteration documented here** — worth pinning down:

- **Windows (hooks → flush.py):** `creationflags=CREATE_NO_WINDOW` (suppresses the console flash). **Not** `DETACHED_PROCESS` — there is an explicit inline comment in `session-end.py` forbidding it: "Do NOT use DETACHED_PROCESS — it breaks the Agent SDK's subprocess I/O."
- **Mac/Linux (hooks → flush.py):** no special flags. The child inherits the parent's session; DEVNULL redirection keeps it from blocking on the parent's closed pipes.

For the second hop — `flush.py` spawning `compile.py` for the end-of-day auto-compilation — stronger isolation *is* used, because compile can run for minutes after the user's session ends:

- **Windows (flush.py → compile.py):** `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`
- **Mac/Linux (flush.py → compile.py):** `start_new_session=True`

The two-tier spawn is deliberate: hooks need the child's I/O cleanly handleable by the Agent SDK (which flush.py itself uses), while the longer-running compile job has to survive after flush.py exits.

**What flush.py does:**
1. Sets `CLAUDE_INVOKED_BY=memory_flush` env var (prevents recursive hook firing)
2. Reads the pre-extracted conversation context from the temp `.md` file
3. Skips if context is empty or if same session was flushed within 60 seconds (deduplication)
4. Calls Claude Agent SDK (`query()` with `allowed_tools=[]`, `max_turns=2`)
5. Claude decides what's worth saving - returns structured bullet points or `FLUSH_OK`
6. Appends result to `raw/daily/YYYY-MM-DD.md`
7. Cleans up temp context file
8. **End-of-day auto-compilation:** If it's past 6 PM local time (`COMPILE_AFTER_HOUR = 18`) and today's daily log has changed since its last compilation (hash comparison against `state.json`), spawns `compile.py` as another detached background process. This means compilation happens automatically once a day without needing a cron job or manual trigger.

### JSONL Transcript Format

Claude Code stores conversations as `.jsonl` files. Messages are usually nested under a `message` key, but some entries place `role` / `content` at the top level, so parsers must fall back:

```python
entry = json.loads(line)
msg = entry.get("message", {})
if isinstance(msg, dict):
    role = msg.get("role", "")
    content = msg.get("content", "")
else:
    # Fallback: some entries have role/content at the top level
    role = entry.get("role", "")
    content = entry.get("content", "")
```

Content can be a string or a list of blocks. Blocks may be dicts (`{"type": "text", "text": "..."}`) or bare strings — see the parsing in `session-end.py:extract_conversation_context` for the full logic.

---

## Script Details

### compile.py - The Compiler

Uses the Claude Agent SDK's async streaming `query()`:

```python
async for message in query(
    prompt=compile_prompt,
    options=ClaudeAgentOptions(
        cwd=str(ROOT_DIR),
        system_prompt={"type": "preset", "preset": "claude_code"},
        allowed_tools=["Read", "Write", "Edit", "Glob", "Grep"],
        permission_mode="acceptEdits",
        max_turns=30,
    ),
):
```

- Builds a prompt with: AGENTS.md schema, current index, the existing-articles section (see modes below), and the daily log
- Claude reads the daily log, decides what concepts to extract, and writes files directly
- `permission_mode="acceptEdits"` auto-approves all file operations
- Incremental: tracks SHA-256 hashes of daily logs in `state.json`, skips unchanged files
- Cost: ~$0.45-0.65 per daily log on small KBs in inline mode; per-file cost grows roughly with wiki size in inline mode and stays roughly constant in lookup mode (see modes below)

**Compile modes (inline vs. lookup):**

The existing-articles section of the prompt is built by `build_articles_context(mode)` in `compile.py`. The `--mode` flag selects between:

- `inline`: every wiki article body is included in the prompt. Maximum grounding; the agent never needs to Read for cross-linking. Becomes expensive at scale and eventually exhausts `max_turns`.
- `lookup`: the existing-articles section is replaced with a one-paragraph instruction telling the agent that bodies are not inlined and that it should Read them on demand from `knowledge/concepts/<slug>.md`, `knowledge/connections/<slug>.md`, or `knowledge/qa/<slug>.md`. The Task section also gains a preamble enforcing a discovery-first step ("identify which existing articles this source may relate to … then use the Read tool … only after Reading should you proceed"). Scales linearly with what each compile actually needs to touch rather than with total wiki size.
- `auto` (default): inline when total wiki bytes < `INLINE_BYTES_THRESHOLD` (500 KB at the top of `compile.py`), else lookup. Re-evaluated per file — a long batch that crosses the threshold mid-run will flip correctly.

The trade-off in `lookup` mode is silent quality drift if the index summaries are too thin to surface relevant articles. The discovery-first preamble plus a future lint check for under-linked new articles are the recommended mitigations.

**CLI:**
```bash
uv run python scripts/compile.py              # compile new/changed only (mode=auto)
uv run python scripts/compile.py --all        # force recompile everything
uv run python scripts/compile.py --file raw/daily/2026-04-01.md
uv run python scripts/compile.py --dry-run
uv run python scripts/compile.py --mode=lookup   # force lookup mode
uv run python scripts/compile.py --mode=inline   # force inline mode
```

### query.py - Index-Guided Retrieval

Loads the entire knowledge base into context (index + all articles). No RAG.

At personal KB scale (50-500 articles), the LLM reading a structured index outperforms vector similarity. The LLM understands what you're really asking; cosine similarity just finds similar words.

Agent SDK options (`scripts/query.py`):

```python
async for message in query(
    prompt=prompt,
    options=ClaudeAgentOptions(
        cwd=str(ROOT_DIR),
        system_prompt={"type": "preset", "preset": "claude_code"},
        allowed_tools=["Read", "Glob", "Grep"],   # +["Write","Edit"] when --file-back
        permission_mode="acceptEdits",
        max_turns=15,
    ),
):
```

`max_turns=15` (half compile.py's 30 — queries don't need the same runway). `Write` and `Edit` are only granted when `--file-back` is set, so a plain query is strictly read-only.

**CLI:**
```bash
uv run python scripts/query.py "What auth patterns do I use?"
uv run python scripts/query.py "What's my error handling strategy?" --file-back
```

With `--file-back`, creates a Q&A article in `knowledge/qa/` and updates the index and log. This is the compounding loop - every question makes the KB smarter.

### lint.py - Health Checks

Seven checks:

| Check | Type | Catches |
|-------|------|---------|
| Broken links | Structural | `[[wikilinks]]` to non-existent articles |
| Orphan pages | Structural | Articles with zero inbound links |
| Orphan sources | Structural | Daily logs not yet compiled |
| Stale articles | Structural | Source logs changed since compilation |
| Missing backlinks | Structural | A links to B but B doesn't link back |
| Sparse articles | Structural | Under 200 words |
| Contradictions | LLM | Conflicting claims across articles |

**CLI:**
```bash
uv run python scripts/lint.py                    # all checks
uv run python scripts/lint.py --structural-only  # skip LLM check (free)
```

Reports saved to `reports/lint-YYYY-MM-DD.md`.

### collect-assets.py - Asset Janitor

Moves stray image files at the project root into `raw/clippings/assets/`. Obsidian Web Clipper drops attachments at the vault root when its attachment-folder setting isn't configured; this script cleans up after it.

- Recognized extensions: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.svg`, `.bmp`
- Only walks the project root (not subdirectories)
- Skips files whose destination already exists — never overwrites
- `--dry-run` prints what would move without touching disk
- Invoked automatically by `session-start.py` on every Claude Code session start (with a 5s timeout; failures swallowed)

**CLI:**
```bash
uv run python scripts/collect-assets.py
uv run python scripts/collect-assets.py --dry-run
```

### link-content.py - Content Setup

Sets up either linked mode (symlinks to a separate content repo) or solo mode (real directories in this checkout). Used once during initial setup; idempotent on re-runs. See "Content models" at the top of this file for the model choice. See `README.md` for the full walkthrough.

- Interactive when invoked with no arguments (`python scripts/link-content.py` or `just setup-content`)
- `--solo` → solo mode, non-interactive
- `<path>` → linked mode, link to an existing content repo
- `<path> --init` → linked mode, create a skeleton + `git init -b main` at `<path>`, then link
- Symlinks are *relative* (e.g. `raw -> ../obsidian-brain-content/raw`), so the two repos can relocate together without breaking
- Refuses to silently cross-switch: rejects `--solo` if symlinks already exist, rejects link mode if non-empty real dirs already exist

---

## State Tracking

`state.json` lives at the content directory root (i.e., `RAW_DIR.resolve().parent` — the content repo in linked mode, the structural-repo root in solo mode), so compile state travels with the content and stays in sync across machines. It tracks:
- `ingested` - map of source file paths (relative to the structural repo root) to SHA-256 hashes, compilation timestamps, and costs
- `query_count` - total queries run
- `last_lint` - timestamp of most recent lint
- `total_cost` - cumulative API cost

`scripts/last-flush.json` tracks flush deduplication (session_id + timestamp). It's host-local and gitignored; not synced across machines.

---

## Dependencies

`pyproject.toml` (at project root):
- `claude-agent-sdk>=0.1.29` - Claude Agent SDK for LLM calls with tool use
- `python-dotenv>=1.0.0` - Environment variable management
- `tzdata>=2024.1` - Timezone data
- Python 3.12+, managed by [uv](https://docs.astral.sh/uv/)

No API key needed - uses Claude Code's built-in credentials at `~/.claude/.credentials.json`.

---

## Costs

> **All cost figures below reflect API pricing.** If you run this system via Claude Code connected to a Claude subscription (Max, Team, or Enterprise), there is **no per-call charge** — usage counts against your subscription's included Claude Code quota, not per-token billing. The cost display in the scripts (`Cost*: $…`) is the API-equivalent, shown for transparency and for users who run on metered API credits.

| Operation | Cost (API pricing) |
|-----------|------|
| Compile one daily log | $0.45-0.65 |
| Query (no file-back) | ~$0.15-0.25 |
| Query (with file-back) | ~$0.25-0.40 |
| Full lint (with contradictions) | ~$0.15-0.25 |
| Structural lint only | $0.00 |
| Memory flush (per session) | ~$0.02-0.05 |

Scripts also print token usage (`input_tokens`, `output_tokens`, and — when applicable — `cache_read_input_tokens` / `cache_creation_input_tokens`) alongside cost via the `format_token_usage()` helper in `scripts/utils.py`.

---

## Customization

### Additional Article Types

Add directories like `people/`, `projects/`, `tools/` to `knowledge/`. Define the article format in this file (AGENTS.md) and update `utils.py`'s `list_wiki_articles()` to include them.

### Obsidian Integration

The knowledge base is pure markdown with `[[wikilinks]]` - works natively in Obsidian. Point a vault at `knowledge/` for graph view, backlinks, and search.

### Scaling Beyond Index-Guided Retrieval

At ~2,000+ articles / ~2M+ tokens, the index becomes too large for the context window. At that point, add hybrid RAG (keyword + semantic search) as a retrieval layer before the LLM. See Karpathy's recommendation of `qmd` for search at scale.
