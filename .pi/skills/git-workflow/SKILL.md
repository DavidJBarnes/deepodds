---
name: git-workflow
description: Enforces clean git branch naming, focused commits, and stale branch cleanup. Use before any git operations.
---

# Git Workflow

**CRITICAL: Before making ANY code changes, create a fresh branch from origin/main.**

Never add new work to an existing branch. Every distinct topic gets its own branch.

## Branch naming

`{type}/{short-description}` — 3-6 words, specific to this change only.

| Prefix | When |
|--------|------|
| `feat/` | New feature or capability |
| `fix/` | Bug fix |
| `docs/` | Documentation only |
| `refactor/` | Code restructuring, no behavior change |

## When user request is a new topic

1. Stash or discard any unrelated changes
2. Checkout origin/main: `git fetch && git checkout main && git pull`
3. Create new branch: `git checkout -b {type}/{short-description}`
4. Make changes and commit
5. Push: `git push -u origin {branch}`

## When user says "push and open PR"

1. Create PR immediately, do NOT add more commits first
2. Use `gh pr create` with a title matching the branch name

## After merge or when moving to a new topic

1. Delete the old branch locally and on origin
2. Close associated PRs
3. Start fresh from main

## Commit messages

- Short first line (under 72 chars)
- No shell-sensitive characters (backticks, dollar signs in body are fine)
