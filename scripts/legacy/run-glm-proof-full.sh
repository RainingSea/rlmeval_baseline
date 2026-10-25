#!/usr/bin/env bash
# GLM-5.3 (lhcodex) codex-agent FULL run on RLM25 PFR+TLB proof track (Easy mode)
set -euo pipefail
cd /data/projects/math-harness-eval/RLMEval
export HOME=/data/projects/math-harness-eval/rlm-env/home
export XDG_CACHE_HOME=$HOME/.cache
export ELAN_HOME=/data/projects/math-harness-eval/elan
RUN_ID=${RUN_ID:-glm53-codex-proof-full-$(date +%Y%m%d-%H%M%S)}
INDICES=${INDICES:-1,2,3,4,5,6,8,9,10,11,12,13,14,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,88,89,91,92,98,99,100,101,102,103,104,105,108,116,117,118,119,120,121,122,123,124,125,126,127,128,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,156,159,161,163,164,165,168,169,170,171,172,173,176,177,179,180,181,182,183,184,185,187,188,189,190,191,192,193,194,196,199,200,201,202,203,204,205,206,207,208,209,210,211,212,213,214,215,216,217,219,220,221,222,223,227,228,229,230,231,232,235,236,237,238,243,244,245,246,248,249,250,251,252,253,254,255,256,257,259,260,264,265,266,267,268,269}
CONC=${CONC:-4}

echo "[$(date -Is)] proof-full start: $RUN_ID items=$(echo $INDICES | tr ',' '\n' | wc -l) conc=$CONC"
./rlmv-eval run-codex \
  --model glm-5.3 \
  --dataset data/rlm25_pfr_tlb.jsonl \
  --indices "$INDICES" \
  --task proof \
  --samples 1 --concurrency "$CONC" --timeout-seconds 2400 --max-compile-attempts 3 \
  --reasoning-effort xhigh \
  --artifacts-dir artifacts \
  --workspaces-dir agent_workspaces \
  --codex-bin run-logs/codex-glm-lhcodex \
  --elan-home "$ELAN_HOME" \
  --cache-dir .rlm-cache \
  --run-id "$RUN_ID"
echo "[$(date -Is)] generation done, scoring start"
./rlmv-eval score \
  --dataset data/rlm25_pfr_tlb.jsonl \
  --input "artifacts/$RUN_ID/generations.jsonl" \
  --output "artifacts/$RUN_ID/scores.jsonl" \
  --task proof
echo "[$(date -Is)] complete: $RUN_ID"
