#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TEMP_DIR=$(mktemp -d)
WORKTREE="$TEMP_DIR/worktree"

cleanup() {
  if [[ -d "$WORKTREE" ]]; then
    git -C "$ROOT" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
  fi
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

if [[ -n "$(git -C "$ROOT" status --porcelain=v1 --untracked-files=all)" ]]; then
  printf 'Clean-room acceptance requires a clean committed worktree.\n' >&2
  exit 1
fi

git -C "$ROOT" worktree add --detach "$WORKTREE" HEAD >/dev/null
cd "$WORKTREE"

python3 -m venv .venv
uv sync --locked --extra dev
npm --prefix web ci

make verify
make doctor
make security-scan
make acceptance-compose
make acceptance-qbittorrent
git diff --exit-code

printf 'Clean-room acceptance passed for %s.\n' "$(git rev-parse HEAD)"
