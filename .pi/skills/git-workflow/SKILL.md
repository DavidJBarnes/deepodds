---
name: git-workflow
description: Enforces clean git branch naming, focused commits, and stale branch cleanup. Use before any git operations.
---

# Git Workflow

Before any commit or push, enforce these rules:

## Branch naming

Branches must follow the convention: `{type}/{short-description}`

| Prefix | When |
|--------|------|
| `feat/` | New feature or capability |
| `fix/` | Bug fix |
| `docs/` | Documentation only |
| `refactor/` | Code restructuring, no behavior change |

The description must be short (3-6 words) and specific to the actual change being made. Examples:
- `feat/add-sol-xrp-doge-scanner` (good)
- `feat/v2-settlement-arb-dashboard` (too long, too vague)
- `fix/ssm-json-quoting` (wrong — branch grew beyond this scope)

## Before committing

1. Check current branch name matches the actual work
2. If not, create a properly named branch from main first
3. Never commit directly to main

## After merging

1. Delete the branch locally and on origin
2. Close the PR

## Commit messages

- Short first line describing the change
- Bullet points for details if needed
- Never include shell-sensitive characters in commit messages
