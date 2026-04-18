---
description: Connect an external Claude Code session to this Obsidian brain — load the structural rules, the knowledge index, and the most recent daily log so the rest of the conversation can draw on accumulated context.
---

# Connect to Obsidian Brain

You are being asked to connect this session to a personal Obsidian knowledge base, which lives in one or two linked repositories following this project's two-repo convention:

- **Structural repo** — scripts, hooks, `.claude/`, rules (this file's repo). Look for a sibling clone; conventionally `obsidian-brain`.
- **Content repo** — raw sources, compiled knowledge, notes. In linked mode this is a separate repo (conventionally `obsidian-brain-content`). In solo mode it's real directories inside the structural repo. Both cases resolve through the same paths (`raw/`, `knowledge/`, `notes/`).

## Finding the vault

Unlike in-brain sessions (which start inside the structural repo and can use `Path(__file__)` resolution), this command is typically invoked from *another* project. You need to find the vault's paths before reading anything.

**Resolution order** (stop at the first that succeeds):

1. Environment variable `OBSIDIAN_BRAIN_ROOT` — if the user exported it, use that as the structural-repo path.
2. `~/obsidian-brain/` — default location.
3. `~/Personal/obsidian-brain/` — alternate convention.
4. `~/Documents/obsidian-brain/` — alternate convention.
5. Ask the user for the path, once.

Use `ls` or `test -d` to probe each candidate. Once you find the structural repo, derive the content paths:

- **Linked mode:** `raw/`, `knowledge/`, `notes/` are symlinks. Follow them: the parent of `$(readlink raw)` is the content repo.
- **Solo mode:** `raw/`, `knowledge/`, `notes/` are real directories inside the structural repo itself. No second path to resolve.

Either way, once you have the structural repo, you can read `raw/*`, `knowledge/*`, `notes/*` through its paths — the scripts and path conventions handle the mode transparently.

Store the resolved paths in your working memory for this session. Don't re-probe.

## What to do, in order

### 1. Load the structural rules (small, essential)

Read in full:

- `$BRAIN/CLAUDE.md`

This teaches the vault's architecture: the `raw/` → LLM → `knowledge/` compiler pattern, the two content-mode options (linked vs solo), and what lives where. ~11KB; fits in context cheaply.

**Do NOT read `AGENTS.md` in full.** It's a long schema. Skim its headings via `grep "^#" $BRAIN/AGENTS.md` if you need it; read specific sections only when a question demands them.

### 2. Load the knowledge index (the catalog)

Read in full:

- `$BRAIN/knowledge/index.md`

This is the master catalog. Every compiled article is listed here with a one-line summary and the sources it was compiled from. When the user asks about a topic, scan this index first — it tells you which file to open. Always load on connect.

### 3. Load the most recent daily log (current thinking)

List files in `$BRAIN/raw/daily/`, find the most recent one (today if it exists, else yesterday), and read it. Daily logs are ~2-5KB each. They capture what the user has been thinking about in the last 1-2 days and often explain the context behind whatever they're about to ask.

### 4. (Optional, on demand) Surface other indexes

The content repo may have additional organizing files. Know these exist but do NOT auto-load:

- `$BRAIN/raw/research/*/contents.md` — per-topic research indexes. Read when the current question touches a research area.
- `$BRAIN/raw/research/*/SESSION-CONTEXT.md` — multi-session brainstorming dumps, relevant if the question touches something that was worked on iteratively.
- `$BRAIN/notes/` — personal scratch space. NOT in the compile pipeline. Use for current thinking, not authoritative knowledge.

### 5. Establish the access pattern for the rest of this session

For the rest of this conversation, treat the vault as read-available through the resolved paths. Specifically:

- **Structural repo paths** (`$BRAIN/` and the tooling inside it): rules, scripts, docs. Read freely; edit only when the user asks for a structural change.
- **Content paths** (through `$BRAIN/raw/`, `$BRAIN/knowledge/`, `$BRAIN/notes/`): read freely. When writing, prefer editing existing files over creating new ones, and respect bucket rules from CLAUDE.md:
  - `raw/daily/` — human-owned; append only
  - `raw/clippings/` — web captures; immutable
  - `raw/research/` — research notes
  - `knowledge/concepts/`, `knowledge/connections/`, `knowledge/qa/` — LLM-owned (compile.py manages); don't hand-write here interactively
  - `notes/` — freeform scratch, safe to edit

- **Commit scope** (if the user asks you to commit):
  - In **linked mode**, structural changes go to the structural repo; content changes go to the content repo — `cd "$(readlink raw)/.."` reaches it.
  - In **solo mode**, there is no second repo; content isn't tracked by the structural repo's `.gitignore` and either stays untracked or is tracked separately by the user.

### 6. Querying efficiently

When the user asks about a topic:

1. **First scan** `knowledge/index.md` (already in context) for matching articles.
2. **Read specific concept/connection files** from `knowledge/concepts/` or `knowledge/connections/` only when the index entry suggests relevance.
3. **Drop down to `raw/`** (the source docs) only when the compiled knowledge is insufficient — e.g., for direct quotes, unresolved research questions, or recent daily-log context that hasn't been compiled yet.
4. **Use Grep** across the content for fuzzy topic discovery: `grep -r "topic" $BRAIN/raw/ $BRAIN/knowledge/` (scope to the right subdir to stay fast).

### 7. Report what you loaded

When steps 1-3 complete, give the user a one-sentence summary like:

> "Brain connected from `<resolved path>`: loaded CLAUDE.md rules, N indexed concepts/connections, and the `<YYYY-MM-DD>` daily log. Ready to draw on it — what are you thinking about?"

Then wait for the user's question. Don't proactively dump summaries — let them drive.

## Important constraints

- **Do not modify the brain unless the user asks.** This is their personal knowledge system. Reading is free; writing requires explicit instruction.
- **Do not confuse repos.** If invoked from a different project, that project's own `CLAUDE.md` / `AGENTS.md` rules still apply for code there. The brain is a *context source*, not a rule replacement.
- **Token economy matters.** CLAUDE.md + index.md + one daily log typically totals 20-30K tokens. Don't load anything else until there's a concrete reason.
- **If a path fails** (broken symlink, missing file), the linked-mode setup is the first suspect. Report the failure; don't guess.

## What this command does NOT do

- It doesn't make this Claude instance *edit* the brain. For that, the user opens Claude Code directly in the structural repo where the compile/lint pipeline and SessionStart hook are wired up.
- It doesn't run `compile.py` or any scripts. Those are session-start activities for the brain repo itself.
- It doesn't replace project-specific context loading. In any other project, that project's AGENTS.md hierarchy still applies on top.

---

Now: resolve the brain path per the "Finding the vault" section above, then execute steps 1, 2, 3, 7.
