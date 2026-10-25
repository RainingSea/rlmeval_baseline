#!/usr/bin/env bash
# GLM-5.3 (lhcodex) codex-agent smoke on RLM25 PFR+TLB — ProofNet-Verified protocol
set -euo pipefail
cd /data/projects/math-harness-eval/RLMEval
export HOME=/data/projects/math-harness-eval/rlm-env/home
export XDG_CACHE_HOME=$HOME/.cache
export ELAN_HOME=${ELAN_HOME:-/data/projects/math-harness-eval/elan}
export PATH="$ELAN_HOME/bin:$PATH"
RUN_ID=${RUN_ID:-glm53-codex-smoke-$(date +%Y%m%d-%H%M%S)}
TASK=${TASK:-statement}
MODEL=${MODEL:-glm-5.3}
CODEX_WRAPPER=${CODEX_WRAPPER:-run-logs/codex-glm-lhcodex}
INDICES=${INDICES:-1,2,3}
REASONING_EFFORT=${REASONING_EFFORT:-xhigh}
CONCURRENCY=${CONCURRENCY:-3}
SAMPLES=${SAMPLES:-1}

./rlmv-eval items \
  --config configs/benchmark/pfr_tlb.yaml \
  --out data/rlm25_pfr_tlb.jsonl \
  --project-map "PFR=/data/projects/math-harness-eval/rlm-env/pfr,TLB=/data/projects/math-harness-eval/rlm-env/tlb"

echo "[$(date -Is)] generation start: $RUN_ID task=$TASK indices=$INDICES"
./rlmv-eval run-codex \
  --model "$MODEL" \
  --dataset data/rlm25_pfr_tlb.jsonl \
  --indices "$INDICES" \
  --samples "$SAMPLES" --concurrency "$CONCURRENCY" --timeout-seconds ${TMO:-1500} --max-compile-attempts 3 \
  --reasoning-effort "$REASONING_EFFORT" \
  --task "$TASK" \
  --artifacts-dir artifacts \
  --workspaces-dir agent_workspaces \
  --codex-bin "$CODEX_WRAPPER" \
  --elan-home "$ELAN_HOME" \
  --cache-dir .rlm-cache \
  --run-id "$RUN_ID"
echo "[$(date -Is)] scoring start"
./rlmv-eval score \
  --dataset data/rlm25_pfr_tlb.jsonl \
  --input "artifacts/$RUN_ID/generations.jsonl" \
  --output "artifacts/$RUN_ID/scores.jsonl" \
  --task "$TASK"
echo "[$(date -Is)] smoke complete: artifacts/$RUN_ID"
