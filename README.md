# LLM Personal Knowledge Base

**Your AI conversations compile themselves into a searchable knowledge base.**

Adapted from [Karpathy's LLM Knowledge Base](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) architecture, but instead of clipping web articles, the raw data is your own conversations with Claude Code. When a session ends (or auto-compacts mid-session), Claude Code hooks capture the conversation transcript and spawn a background process that uses the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk) to extract the important stuff - decisions, lessons learned, patterns, gotchas - and appends it to a daily log. You then compile those daily logs into structured, cross-referenced knowledge articles organized by concept. Retrieval uses a simple index file instead of RAG - no vector database, no embeddings, just markdown.

Anthropic has clarified that personal use of the Claude Agent SDK is covered under your existing Claude subscription (Max, Team, or Enterprise) - no separate API credits needed. Unlike OpenClaw, which requires API billing for its memory flush, this runs on your subscription.

## Repository architecture

This project ships the **tooling** (scripts, hooks, docs, `.claude/` config) in a public repository. Your **knowledge** lives separately — either inside your checkout of this repo (gitignored) or in a private companion repo linked via symlinks. Either way, personal content never leaks into the public structural repo.

The three content directories (`raw/`, `knowledge/`, `notes/`) are gitignored here; every tool in the project operates on those paths regardless of whether they're real folders or symlinks.

## Setup

```bash
git clone git@github.com:radif/obsidian-brain.git
cd obsidian-brain
./scripts/setup.sh       # installs just, uv, Python deps
just setup-content       # interactive: pick a content model
```

`just setup-content` prompts you to choose one of two content models:

### Option 1: Solo — content stays in this checkout

`raw/`, `knowledge/`, `notes/` become real directories inside this working directory. They're gitignored in the structural repo, so they never reach the public repo. You version them however you like (or not at all).

Non-interactive equivalent:
```bash
just solo
```

Good for: trying out the system, single-machine use, keeping the footprint minimal. You can migrate to Option 2 later — see "Switching modes" below.

### Option 2: Two-repo with symlinks (recommended)

`raw/`, `knowledge/`, `notes/` become **relative symlinks** (e.g. `raw -> ../obsidian-brain-content/raw`) into a separate private git repo. Gives you version history, off-site backup via GitHub, and cross-machine sync. Relative symlinks mean the structural + content pair can be relocated together without breaking the link.

1. Create the private content repo on GitHub (`gh repo create <you>/obsidian-brain-content --private`).
2. Initialize + link:
   ```bash
   just init-content ../obsidian-brain-content
   ```
   This creates a skeleton (`raw/daily/`, `raw/clippings/`, `knowledge/{concepts,connections,qa}/`, `notes/`), runs `git init -b main`, and symlinks the three content directories into this working directory. If you already have a content repo cloned, use `just link-content <path>` instead. The sibling path is just convention — anything works.
3. Wire up the remote + (recommended) LFS in the content repo:
   ```bash
   cd ../obsidian-brain-content
   git remote add origin git@github.com:<you>/obsidian-brain-content.git
   git lfs install
   git lfs track "*.pdf" "*.png" "*.jpg" "*.jpeg" "*.gif" "*.webp" "*.heic"
   git add .gitattributes .gitignore README.md
   git commit -m "Initial content repo setup"
   git push -u origin main
   ```
   LFS matters once you accumulate image-heavy Web Clipper captures or PDFs. GitHub's free LFS tier (1 GB storage, 1 GB bandwidth/month) covers most personal KBs.

### Finishing up

Open the structural repo in Claude Code — hooks activate automatically. Sessions are captured into `raw/daily/`, the knowledge index is injected on session start, and compilation runs automatically after 6 PM local time.

### Switching modes

- **Solo → linked.** Move the local directories into a new content repo, then symlink them back:
  ```bash
  mkdir -p ../obsidian-brain-content && (cd ../obsidian-brain-content && git init -b main)
  mv raw knowledge notes ../obsidian-brain-content/
  just link-content ../obsidian-brain-content
  just compile-dry    # should report nothing to do — cache survived the move
  ```
  The compile cache is content-addressed (SHA-256 of bytes) with lexical path keys, so moving the bytes doesn't invalidate anything. No recompile triggered.

- **Linked → solo.** Remove the symlinks, move the content back:
  ```bash
  rm raw knowledge notes
  mv ../obsidian-brain-content/{raw,knowledge,notes} .
  ```
  (The content repo is now empty apart from `.git/`; delete it if you don't want it anymore.)

## How It Works

```
Conversation -> SessionEnd/PreCompact hooks -> flush.py extracts knowledge
    -> raw/daily/YYYY-MM-DD.md -> compile.py -> knowledge/concepts/, connections/, qa/
        -> SessionStart hook injects index into next session -> cycle repeats
```

Other raw sources drop into sibling buckets under `raw/` — e.g. `raw/clippings/`
for Obsidian Web Clipper output, `raw/research/` for long-form notes and papers,
or any new bucket you create with `mkdir raw/<name>`. All of them flow through
the same compile pipeline. Any immediate subdirectory of `raw/` is
auto-discovered; no code changes needed to add a new source type.

- **Hooks** capture conversations automatically (session end + pre-compaction safety net)
- **flush.py** calls the Claude Agent SDK to decide what's worth saving, and after 6 PM triggers end-of-day compilation automatically
- **compile.py** turns daily logs into organized concept articles with cross-references (triggered automatically or run manually)
- **query.py** answers questions using index-guided retrieval (no RAG needed at personal scale)
- **lint.py** runs 7 health checks (broken links, orphans, contradictions, staleness)

## Key Commands

All commands are wrapped as [`just`](https://github.com/casey/just) recipes. Run `just` (or `just --list`) to see them all.

```bash
./scripts/setup.sh              # one-time: install just, uv, and Python deps
just compile                    # compile new/changed raw files
just compile-all                # force full recompile
just compile-dry                # preview without writing
just ask "question"             # ask the knowledge base
just ask-save "question"        # ask + save answer to knowledge/qa/
just lint                       # run all health checks
just lint-structural            # free structural checks only
just flush                      # manually flush a session transcript
just collect-assets             # move stray root images into raw/clippings/assets/
just collect-assets-dry         # preview asset moves
```

## Why No RAG?

Karpathy's insight: at personal scale (50-500 articles), the LLM reading a structured `index.md` outperforms vector similarity. The LLM understands what you're really asking; cosine similarity just finds similar words. RAG becomes necessary at ~2,000+ articles when the index exceeds the context window.

## Technical Reference

See **[AGENTS.md](AGENTS.md)** for the complete technical reference: article formats, hook architecture, script internals, cross-platform details, costs, and customization options. AGENTS.md is designed to give an AI agent everything it needs to understand, modify, or rebuild the system.
