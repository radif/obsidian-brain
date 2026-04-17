---
name: kb-setup
description: Use when the user is bootstrapping this project on a new machine or has just cloned it and needs dependencies installed. Runs `./scripts/setup.sh` which installs just, uv, and Python deps (idempotent).
---

Run `./scripts/setup.sh` via the Bash tool. Report what was installed versus what was already present. Setup is idempotent, so re-running it is safe.
