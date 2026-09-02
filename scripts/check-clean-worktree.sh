#!/usr/bin/env bash

set -euo pipefail

git diff HEAD --check
git diff HEAD --exit-code

worktree_status="$(git status --porcelain=v1 --untracked-files=all)"
if [[ -n "$worktree_status" ]]; then
  printf '%s\n' "$worktree_status"
  exit 1
fi
