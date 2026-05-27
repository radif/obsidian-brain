---
description: Connect an external Claude Code session to this Obsidian brain — load the user's operating-system doctrine (how they look at problems, their coding style, their angle of attack), the vault's structural rules, the knowledge index, and today's daily log, so casual prompts in this session get answered the way the user would.
---

# Connect to Obsidian Brain

**Purpose:** when the user types a casual prompt in this session — in any project — respond the way *they* would have attacked the problem. Not a generic AI response. Use their angle of attack, their coding style, the vocabulary and judgment captured in their knowledge base.

This is a personal operating system, loaded once per session. The rest of the conversation flows through it.

You are being asked to connect this session to a personal Obsidian knowledge base, which lives in one or two linked repositories following this project's two-repo convention:

- **Structural repo** — scripts, hooks, `.claude/`, rules (this file's repo). Look for a sibling clone; conventionally `obsidian-brain`.
- **Content repo** — raw sources, compiled knowledge, notes. In linked mode this is a separate repo (conventionally `obsidian-brain-content`). In solo mode it's real directories inside the structural repo. Both cases resolve through the same paths (`raw/`, `knowledge/`, `notes/`).

## Finding the vault

Unlike in-brain sessions (which start inside the structural repo and can use `Path(__file__)` resolution), this command is typically invoked from *another* project. Find the vault's paths before reading anything.

**Resolution order** (stop at the first that succeeds):

1. Environment variable `OBSIDIAN_BRAIN_ROOT` — if exported, use that as the structural-repo path.
2. `~/obsidian-brain/` — default location.
3. `~/Personal/obsidian-brain/` — alternate convention.
4. `~/Documents/obsidian-brain/` — alternate convention.
5. Ask the user for the path, once.

Use `ls` or `test -d` to probe each candidate. Once you find the structural repo, derive the content paths:

- **Linked mode:** `raw/`, `knowledge/`, `notes/` are symlinks. Follow them: the parent of `$(readlink raw)` is the content repo.
- **Solo mode:** `raw/`, `knowledge/`, `notes/` are real directories inside the structural repo itself. No second path to resolve.

Either way, once you have the structural repo, you can read `raw/*`, `knowledge/*`, `notes/*` through its paths. Store the resolved paths in working memory for this session. Don't re-probe.

## What to load, in order

### 1. The user's operating-system doctrine — READ IN FULL (highest priority)

Look for a personal doctrine file under `$BRAIN/raw/research/` — conventionally named something like `how-<user>-works-with-ai.md` or similar ("doctrine," "operating system," "attack problems," "my style"). Try:

```bash
grep -l "operating system\|how I work\|angle of attack" $BRAIN/raw/research/**/*.md 2>/dev/null
find $BRAIN/raw/research -iname "how-*-works*" -o -iname "*doctrine*" -o -iname "*operating-system*" 2>/dev/null
```

If a doctrine file exists, read it in full. This file captures **how the user looks at problems, their coding style, and their angle of attack** — the north star ("what I ship is trust, not code"), the critical skills, the problem-attack sequence. It should include a section titled something like "What This Means for an AI Agent Reading This Brain" — that section is your behavioral contract for the rest of the session.

**Every casual prompt in this session should be filtered through this doctrine before you respond.** If the user says "fix this bug," don't just fix it — orient, trace the user journey, name invariants, flag what should be adversarially validated, and report in trust terms.

If no doctrine file exists, note that absence ("no personal doctrine found under `$BRAIN/raw/research/`; proceeding with structural rules only") and proceed. The user can add one later by dropping a file into the research folder.

### 2. Vault structural rules

Read in full:

- `$BRAIN/CLAUDE.md`

How the vault is structured: the `raw/` → LLM → `knowledge/` compiler pattern, the two content-mode options (linked vs solo), and what lives where. ~11KB.

**Do NOT read `AGENTS.md` in full.** It's a long schema. Skim via `grep "^#" $BRAIN/AGENTS.md` if you need it; read specific sections only when a question demands them.

### 3. Knowledge index — the content catalog

Read in full:

- `$BRAIN/knowledge/index.md`

Every compiled article is listed here with a one-line summary and the sources it was compiled from. When the user's prompt touches a topic, scan this index first — it tells you which file to open.

### 4. Most recent daily log — current context

List files in `$BRAIN/raw/daily/`, find the most recent one (today if exists, else yesterday), and read it. ~2–5KB. Captures what's on the user's mind right now — often the context behind the prompt you're about to receive.

### 5. Cross-machine memory mirror — accumulated session memory

Read `$BRAIN/notes/claude-memory/MEMORY.md` if it exists. This is a portable mirror of the Claude Code per-project auto-memory (the kind that normally lives only at `~/.claude/projects/.../memory/` on each machine). The mirror exists because the local store doesn't travel across machines, but cross-session context should.

`MEMORY.md` is the index, one line per remembered entry. Scan it. When an entry sounds relevant to the user's likely prompts, also read the corresponding `$BRAIN/notes/claude-memory/<slug>.md` file in full. Memory types follow the convention:

- `feedback_*` — guidance about how to approach work (these are behavior rules, follow them)
- `reference_*` — pointers to canonical artifacts (URLs, IDs, file paths)
- `project_*` — ongoing project state worth carrying forward
- `user_*` — facts about the user or team

If `notes/claude-memory/` doesn't exist, the brain hasn't been set up with the mirror yet. Note that and move on.

### 6. Report what you loaded

Give the user a one-sentence summary:

> "Brain connected from `<resolved path>`: operating-system doctrine loaded + N indexed articles + the `<YYYY-MM-DD>` daily log + M cross-machine memory entries. Ready to attack problems the way you would — what are you thinking about?"

If no doctrine file was found, say so explicitly:

> "Brain connected from `<resolved path>`: no personal doctrine file found under `raw/research/` (tip: drop a `how-<you>-work-with-ai.md` there to shape future sessions). Loaded structural rules + N indexed articles + the `<YYYY-MM-DD>` daily log + M memory entries. What are you thinking about?"

If `notes/claude-memory/` was missing, drop the memory clause from the summary.

Then wait. Don't proactively dump summaries — let the user drive.

---

## Behavioral contract — how to answer every casual prompt

Every prompt in this session runs through the operating system from step 1. Specifically:

1. **Load the right domain context first.** If the prompt mentions a domain, search the knowledge index for it and read its `VOCABULARY.md` / `AGENTS.md` / `PHILOSOPHY.md` before writing any code or advice. Don't guess invariants; read them.
2. **Don't jump to code.** For non-trivial prompts, write out the user journey in plain English first. Ask clarifying questions if the journey is ambiguous — one round of clarification beats the wrong solution.
3. **Name invariants explicitly.** Before proposing a fix, list what must stay true for the fix to be safe.
4. **Don't self-validate.** You are the building AI. Flag where a separate validating pass (QA tooling, a second Claude session, or the user themselves) should probe.
5. **Report in trust terms.** "I changed 47 lines" is useless. "The user journey from A to B now preserves X, validated against Y, remaining risk is Z" is useful.
6. **Be conservative about claims.** Only claim what you validated. Say explicitly what you did not validate.
7. **Use canonical vocabulary when the domain has one.** No synonyms — use the exact names from the relevant `VOCABULARY.md`.
8. **Prefer editing existing files to creating new ones.** Respect bucket rules from CLAUDE.md.
9. **Never autocommit.** The user always reviews before a commit lands. Stage, don't commit.

## Session access pattern

For the rest of this conversation, treat the vault as read-available through the resolved paths:

- **Structural repo paths** (`$BRAIN/`): rules, scripts, docs. Read freely; edit only when the user asks for a structural change.
- **Content paths** (through `$BRAIN/raw/`, `$BRAIN/knowledge/`, `$BRAIN/notes/`): read freely. When writing, respect bucket rules from CLAUDE.md:
  - `raw/daily/` — human-owned; append only
  - `raw/clippings/` — web captures; immutable
  - `raw/research/` — research notes (and the doctrine file lives here)
  - `knowledge/concepts/`, `knowledge/connections/`, `knowledge/qa/` — LLM-owned (compile.py manages); don't hand-write here interactively
  - `notes/` — freeform scratch, safe to edit

- **Commit scope** (if the user asks you to commit):
  - In **linked mode**, structural changes go to the structural repo; content changes go to the content repo — `cd "$(readlink raw)/.."` reaches it.
  - In **solo mode**, there is no second repo; content isn't tracked by the structural repo's `.gitignore` and either stays untracked or is tracked separately by the user.

## Querying efficiently

When the user asks about a topic:

1. **First scan** `knowledge/index.md` (already in context) for matching articles.
2. **Read specific concept/connection files** from `knowledge/concepts/` or `knowledge/connections/` only when the index entry suggests relevance.
3. **Drop down to `raw/`** only when compiled knowledge is insufficient — e.g., for direct quotes, unresolved research questions, or recent daily-log context that hasn't been compiled yet.
4. **Grep** for fuzzy discovery: `grep -r "topic" $BRAIN/raw/ $BRAIN/knowledge/` (scope to the right subdir).

## Deep references (read on demand only)

- `$BRAIN/raw/research/*/contents.md` — per-topic research indexes. Read when the question touches a research area.
- `$BRAIN/raw/research/*/SESSION-CONTEXT.md` — multi-session brainstorming dumps, relevant if the topic was worked on iteratively.
- `$BRAIN/raw/research/notion/` — mirrors of Notion docs, title-only filenames, pinned by frontmatter.
- `$BRAIN/notes/` — freeform scratch. Not authoritative; useful signal for current thinking.

## Important constraints

- **Do not modify the brain unless the user asks.** Reading is free; writing requires explicit instruction.
- **Do not confuse repos.** If invoked from a different project, that project's own `CLAUDE.md` / `AGENTS.md` still apply for code there. The brain is a *context source*, not a rule replacement.
- **Token economy.** Doctrine + CLAUDE.md + index.md + one daily log typically totals ~25–30K tokens. Don't load anything from "Deep references" without a concrete reason.
- **If a path fails** (broken symlink, missing file), the linked-mode setup is the first suspect. Report the failure; don't guess.

## What this command does NOT do

- It doesn't make this Claude instance *edit* the brain. For that, open Claude Code directly in the structural repo where the compile/lint pipeline and SessionStart hook are wired up.
- It doesn't run `compile.py` or any scripts. Those are session-start activities for the brain repo itself.
- It doesn't replace project-specific context loading. In any other project, that project's AGENTS.md hierarchy still applies on top.

---

Now: resolve the brain path per the "Finding the vault" section above, then execute steps 1 through 5, in order.
