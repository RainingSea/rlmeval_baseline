#!/usr/bin/env bash
set -euo pipefail
BASE=/data/projects/math-harness-eval
export ELAN_HOME="$BASE/elan"
export HOME="$BASE/rlm-env/home"
export XDG_CACHE_HOME="$HOME/.cache"
export GIT_CONFIG_GLOBAL=/dev/null
export PATH="$ELAN_HOME/bin:$PATH"
mkdir -p "$XDG_CACHE_HOME"
for repo in pfr tlb; do
  cd "$BASE/rlm-env/$repo"
  echo "[$(date -Is)] $repo: $(cat lean-toolchain)"
  lake exe cache get 2>&1 | tail -2
  lake build 2>&1 | tail -3
  echo "[$(date -Is)] $repo: BUILD DONE"
done
