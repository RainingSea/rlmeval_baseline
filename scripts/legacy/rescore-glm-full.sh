#!/usr/bin/env bash
set -euo pipefail

cd /data/projects/math-harness-eval/RLMEval

RUN_DIR=${RUN_DIR:-run-logs/glm-full-rescore-$(date +%Y%m%d-%H%M%S)}
mkdir -p "$RUN_DIR"

echo "[$(date -Is)] GLM TLB rescore start"
RUN_ID=glm53-tlb124-easy-pass1-20261017-114645 EXPECTED_SAMPLES=1 SKIP_IF_VERIFIED=1 \
  bash scripts/rescore-codex-run.sh

echo "[$(date -Is)] GLM PFR rescore start"
RUN_ID=glm53-pfr145-easy-pass1-20261017-143909 EXPECTED_SAMPLES=1 SKIP_IF_VERIFIED=1 \
  bash scripts/rescore-codex-run.sh

{
  echo "# GLM Full Rescore"
  echo
  echo "- Completed: $(date -Is)"
  echo
  sed -n '1,12p' run-logs/glm53-tlb124-easy-pass1-20261017-114645/summary.md
  echo
  sed -n '1,12p' run-logs/glm53-pfr145-easy-pass1-20261017-143909/summary.md
} > "$RUN_DIR/summary.md"

echo "[$(date -Is)] GLM full rescore complete"
echo "summary=$RUN_DIR/summary.md"
