#!/usr/bin/env bash
set -euo pipefail
BASE=/data/projects/math-harness-eval
export HOME="$BASE/rlm-env/home"
export XDG_CACHE_HOME="$HOME/.cache"
export ELAN_HOME="$HOME/.elan"
export PATH="$ELAN_HOME/bin:$PATH"
export GIT_CONFIG_GLOBAL=/dev/null
export LEAN_DOJO_NO_GITHUB_API=1
export TMPDIR="$BASE/rlm-env/tmp"
export TMP="$TMPDIR"
export RAY_TMPDIR=/tmp
mkdir -p "$TMPDIR"
cd "$BASE/RLMEval"
mkdir -p traced_repos
exec /root/miniconda3/envs/rlmeval/bin/python scripts/extract_benchmark.py --config configs/benchmark/pfr_tlb.yaml
