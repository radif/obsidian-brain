"""
Cross-machine git sync for the knowledge base.

Keeps both repos this engine spans in sync across machines:

  - structural repo = this checkout (ROOT)         git@.../obsidian-brain
  - content repo    = raw/.resolve().parent        git@.../obsidian-brain-content

In solo mode the two paths are identical and get deduplicated to one repo.

Two subcommands, mapped to the two ends of a session:

  pull   Fetch + merge BOTH repos so a new session starts current. Run from the
         SessionStart hook. Does NOT push. Does NOT auto-resolve conflicts: if a
         merge can't complete cleanly it leaves the repo mid-merge ON PURPOSE
         and prints an action-required block, so the interactive Claude session
         resolves the conflict at launch (per the user's instruction).

  push   Commit staged changes, then fetch + merge, then push the CONTENT repo
         only. Run from flush.py's tail (after the daily log is written) and from
         session-end.py's skip paths. The pre-push fetch + merge prevents a
         non-fast-forward rejection when another machine pushed mid-session;
         because this runs headless (no Claude to resolve), a clean/ff merge
         proceeds to push while a genuine conflict is aborted and DEFERRED to the
         next launch pull. The structural repo is NEVER auto-pushed — engine code
         is pushed manually, with a real commit message. (In solo mode the
         content repo is this checkout, so it's still the one pushed.)

Design rules:
  - Prints a markdown summary to stdout (captured by session-start.py and
    injected into session context, or shown on the CLI).
  - ALWAYS exits 0. A sync problem is surfaced as text; it must never crash a
    hook or abort a flush.
  - No LLM / Agent SDK calls — pure git subprocess work, fast and offline-safe.

Usage:
    uv run python scripts/sync.py pull
    uv run python scripts/sync.py push
"""

from __future__ import annotations

import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FETCH_TIMEOUT = 18   # seconds — bounded so the SessionStart hook can't hang
PUSH_TIMEOUT = 60    # seconds — flush.py is detached, so it can afford more
LOCAL_TIMEOUT = 15   # seconds — local git ops (add/commit/merge/rev-list)


def _git(repo: Path, *args: str, timeout: int = LOCAL_TIMEOUT) -> tuple[int, str, str]:
    """Run `git -C <repo> <args>`; return (returncode, stdout, stderr).

    A timeout or spawn failure is mapped to returncode 1 with the error in
    stderr, so callers can treat it like any other git failure.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", f"git {' '.join(args)} timed out after {timeout}s"
    except (FileNotFoundError, OSError) as e:
        return 1, "", str(e)


def _discover_repos() -> list[tuple[str, Path]]:
    """Return [(label, path)] for each git repo to sync, deduped by real path.

    Structural repo first, then the content repo (raw/.resolve().parent). In
    solo mode they collapse to one. Non-git paths and remotes-less repos are
    dropped silently — sync is best-effort.
    """
    candidates: list[tuple[str, Path]] = [("structural", ROOT)]

    content = (ROOT / "raw").resolve().parent
    candidates.append(("content", content))

    repos: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for label, path in candidates:
        try:
            real = path.resolve()
        except OSError:
            continue
        if real in seen:
            continue
        rc, out, _ = _git(real, "rev-parse", "--is-inside-work-tree")
        if rc != 0 or out != "true":
            continue
        rc, out, _ = _git(real, "remote")
        if rc != 0 or not out.strip():
            continue
        seen.add(real)
        repos.append((label, real))
    return repos


def _branch(repo: Path) -> str | None:
    rc, out, _ = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0 or out == "HEAD" or not out:
        return None  # detached HEAD or error
    return out


def _has_staged(repo: Path) -> bool:
    """True iff the index has staged changes (`git diff --cached --quiet` → 1)."""
    rc, _, _ = _git(repo, "diff", "--cached", "--quiet")
    return rc == 1


def _count_changes(repo: Path) -> int:
    """Count working-tree entries (staged + unstaged + untracked) — for reporting."""
    rc, out, _ = _git(repo, "status", "--porcelain")
    if rc != 0:
        return 0
    return len([ln for ln in out.splitlines() if ln.strip()])


def _count(repo: Path, rev_range: str) -> int:
    rc, out, _ = _git(repo, "rev-list", "--count", rev_range)
    if rc != 0:
        return 0
    try:
        return int(out.strip())
    except ValueError:
        return 0


def _stamp() -> str:
    host = socket.gethostname().split(".")[0]
    when = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    return f"{host} {when}"


def _name(repo: Path) -> str:
    return repo.name


# ── pull ────────────────────────────────────────────────────────────────

def _pull_repo(label: str, repo: Path) -> tuple[str, bool]:
    """Pull one repo. Returns (markdown_line_or_block, needs_resolution)."""
    tag = f"**{_name(repo)}** ({label})"

    branch = _branch(repo)
    if branch is None:
        return f"- {tag}: ⚠️ detached HEAD — skipped", False

    rc, _, err = _git(repo, "fetch", "origin", branch, timeout=FETCH_TIMEOUT)
    if rc != 0:
        return f"- {tag}: fetch failed ({err.splitlines()[0] if err else 'unknown'}) — skipped", False

    upstream = f"origin/{branch}"
    behind = _count(repo, f"HEAD..{upstream}")
    if behind == 0:
        return f"- {tag}: up to date", False

    # We are behind; a merge is needed. Commit only what the session STAGED
    # (never `git add -A`) so the merge can proceed and any real conflicts
    # surface as markers — without sweeping stray/untracked files into history.
    if _has_staged(repo):
        _git(repo, "commit", "-m", f"auto: pre-sync snapshot of staged work ({_stamp()})")

    rc, _, err = _git(repo, "merge", "--no-edit", upstream)
    if rc == 0:
        return f"- {tag}: merged {behind} commit(s) from {upstream} — clean", False

    # rc != 0 is one of two cases: a real conflict (unmerged paths with markers),
    # or git refusing to start the merge because uncommitted local changes are in
    # the way. Distinguish by checking for unmerged paths.
    _, conflicted, _ = _git(repo, "diff", "--name-only", "--diff-filter=U")
    files = [f for f in conflicted.splitlines() if f.strip()]
    if files:
        # Real conflict: left mid-merge on purpose for Claude to resolve.
        file_lines = "\n".join(f"  - `{f}`" for f in files)
        block = (
            f"- {tag}: ⚠️ **MERGE CONFLICT — resolve before proceeding**\n"
            f"  - repo: `{repo}`\n"
            f"  - conflicted files:\n{file_lines}"
        )
        return block, True

    # Merge refused; working tree is intact. Uncommitted local changes block it.
    first = err.splitlines()[0] if err else "merge blocked by local uncommitted changes"
    block = (
        f"- {tag}: ⚠️ **MERGE BLOCKED — resolve before proceeding**\n"
        f"  - repo: `{repo}`\n"
        f"  - {first}\n"
        f"  - Local uncommitted changes are in the way. Stage & commit the ones you "
        f"want to keep (`git -C {repo} add <files> && git -C {repo} commit`), or "
        f"stash them, then re-run `uv run python scripts/sync.py pull`."
    )
    return block, True


def cmd_pull() -> None:
    repos = _discover_repos()
    if not repos:
        print("## 🔄 Repo sync (launch pull)\n\n_No syncable git repos found._")
        return

    lines: list[str] = []
    any_conflict = False
    for label, repo in repos:
        line, needs = _pull_repo(label, repo)
        lines.append(line)
        any_conflict = any_conflict or needs

    header = "## 🔄 Repo sync (launch pull)"
    if any_conflict:
        header += " — ⚠️ ACTION REQUIRED"

    out = [header, "", *lines]

    if any_conflict:
        out += [
            "",
            "One or more repos were left **mid-merge on purpose** so you can "
            "resolve the conflict now, before doing anything else this session. "
            "For each conflicted file, open it and reconcile the "
            "`<<<<<<<` / `=======` / `>>>>>>>` markers — daily logs "
            "(`raw/daily/*.md`) and `knowledge/log.md` are **append-only**, so "
            "the right resolution is almost always to keep BOTH sides' content. "
            "Then stage just the resolved files and commit: "
            "`git -C <repo> add <resolved files> && git -C <repo> commit --no-edit` "
            "(stage only what you resolved — the end-of-session push commits the "
            "index, so don't `git add -A` stray files in). Do this before other "
            "work; the push at session end depends on a clean tree.",
        ]

    print("\n".join(out))


# ── push ────────────────────────────────────────────────────────────────

def _push_repo(label: str, repo: Path) -> str:
    tag = f"**{_name(repo)}** ({label})"

    branch = _branch(repo)
    if branch is None:
        return f"- {tag}: ⚠️ detached HEAD — skipped"

    # Refuse to push a tree still mid-conflict (unresolved merge from launch).
    _, conflicted, _ = _git(repo, "diff", "--name-only", "--diff-filter=U")
    if conflicted.strip():
        return f"- {tag}: ⚠️ unresolved merge conflict — not pushing (resolve first)"

    # Commit ONLY what the session staged. We deliberately never `git add` here,
    # so stray files (Playwright PNGs, scratch JSON/YAML, anything untracked or
    # merely modified-but-not-staged) can never be committed. Writers stage
    # their own output: flush.py stages the daily-log entry it writes;
    # interactive Claude stages the content files it edits.
    if _has_staged(repo):
        rc, _, err = _git(repo, "commit", "-m", f"auto: session sync ({_stamp()})")
        if rc != 0 and "nothing to commit" not in (err or "").lower():
            return f"- {tag}: commit failed ({err.splitlines()[0] if err else 'unknown'})"

    # Pull + merge BEFORE pushing so a concurrent push from another machine
    # doesn't reject ours as non-fast-forward. This runs headless (no Claude to
    # resolve a conflict), so the rule is: clean merge / fast-forward → continue
    # and push; a genuine conflict → abort the merge and DEFER (don't push). The
    # next launch pull surfaces it for interactive resolution.
    rc, _, ferr = _git(repo, "fetch", "origin", branch, timeout=FETCH_TIMEOUT)
    if rc != 0:
        first = ferr.splitlines()[0] if ferr else "unknown"
        return f"- {tag}: pre-push fetch failed ({first}) — not pushing"
    if _count(repo, f"HEAD..origin/{branch}") > 0:
        rc, _, merr = _git(repo, "merge", "--no-edit", f"origin/{branch}")
        if rc != 0:
            _git(repo, "merge", "--abort")
            return (
                f"- {tag}: ⚠️ remote diverged and the pre-push merge conflicted — "
                f"aborted, not pushed (resolve at next launch pull)"
            )

    ahead = _count(repo, f"origin/{branch}..HEAD")
    if ahead == 0:
        leftover = _count_changes(repo)
        if leftover:
            return (
                f"- {tag}: nothing staged to push "
                f"({leftover} uncommitted change(s) left unstaged — stage them "
                f"during the session to sync)"
            )
        return f"- {tag}: nothing to push"

    rc, _, err = _git(repo, "push", "origin", branch, timeout=PUSH_TIMEOUT)
    if rc == 0:
        return f"- {tag}: pushed {ahead} commit(s)"
    first = err.splitlines()[0] if err else "unknown"
    return f"- {tag}: ⚠️ push failed ({first}) — will reconcile at next launch pull"


def _content_repo() -> tuple[str, Path] | None:
    """The content repo — the ONLY repo auto-pushed at session end.

    Structural-repo pushes are manual by design (engine code lands deliberately,
    with a real commit message — not an auto `git add -A`). In solo mode the
    content repo IS this checkout (raw/ is a real dir), so the same path is
    returned and still gets pushed, since it holds all the content.

    Returns (label, path) or None if there's no syncable content git repo.
    """
    try:
        real = (ROOT / "raw").resolve().parent.resolve()
    except OSError:
        return None
    rc, out, _ = _git(real, "rev-parse", "--is-inside-work-tree")
    if rc != 0 or out != "true":
        return None
    rc, out, _ = _git(real, "remote")
    if rc != 0 or not out.strip():
        return None
    label = "content (solo — this checkout)" if real == ROOT.resolve() else "content"
    return label, real


def cmd_push() -> None:
    header = "## 🔄 Repo sync (session-end push)"
    target = _content_repo()
    if target is None:
        print(f"{header}\n\n_No syncable content repo found._")
        return
    label, repo = target
    print("\n".join([
        header,
        "",
        _push_repo(label, repo),
        "",
        "_Structural repo is not auto-pushed — its pushes are manual._",
    ]))


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "pull":
        cmd_pull()
    elif action == "push":
        cmd_push()
    else:
        print("usage: sync.py {pull|push}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
