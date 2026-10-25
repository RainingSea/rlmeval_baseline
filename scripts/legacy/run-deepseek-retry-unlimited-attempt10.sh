#!/usr/bin/env bash
set -euo pipefail

cd /data/projects/math-harness-eval/RLMEval

BATCH_ID=${BATCH_ID:-deepseek-v4-pro-retry-unlimited-a10-$(date +%Y%m%d-%H%M%S)}
BATCH_DIR=${BATCH_DIR:-run-logs/$BATCH_ID}
CONCURRENCY_PER_DATASET=${CONCURRENCY_PER_DATASET:-2}

TLB_INDICES=147,149,152,154,156,157,160,162,164,170,171,172,182,183,186,188,191,199,200,201,202,207,212,213,220,228,232,235,243,248,249,251,252,258,259,262,267,268
PFR_INDICES=10,24,28,32,36,41,45,49,50,52,53,55,58,59,60,63,65,66,76,78,80,83,87,94,95,97,100,101,104,106,107,110,111,112,113,119,131,132,133,134,137

TLB_RUN_ID=${TLB_RUN_ID:-$BATCH_ID-tlb38}
PFR_RUN_ID=${PFR_RUN_ID:-$BATCH_ID-pfr41}

mkdir -p "$BATCH_DIR"
printf '%s\n' "$TLB_INDICES" > "$BATCH_DIR/tlb-indices.txt"
printf '%s\n' "$PFR_INDICES" > "$BATCH_DIR/pfr-indices.txt"

cat > "$BATCH_DIR/config.txt" <<CONFIG
BATCH_ID=$BATCH_ID
MODEL=deepseek-v4-pro
TASK=proof
SAMPLES=1
REASONING_EFFORT=high
TMO=0
MAX_COMPILE_ATTEMPTS=10
CONCURRENCY_PER_DATASET=$CONCURRENCY_PER_DATASET
TLB_RUN_ID=$TLB_RUN_ID
PFR_RUN_ID=$PFR_RUN_ID
TLB_ITEMS=38
PFR_ITEMS=41
CONFIG

echo "[$(date -Is)] launching TLB 38 and PFR 41 retry runs"

RUN_ID="$TLB_RUN_ID" \
MODEL=deepseek-v4-pro \
TASK=proof \
INDICES="$TLB_INDICES" \
SAMPLES=1 \
CONCURRENCY="$CONCURRENCY_PER_DATASET" \
REASONING_EFFORT=high \
TMO=0 \
MAX_COMPILE_ATTEMPTS=10 \
CODEX_WRAPPER=run-logs/codex-gpt-custom \
SECRET_FILE=secret.txt \
SOURCE_SECRET=1 \
SUMMARY_DIR="run-logs/$TLB_RUN_ID" \
bash scripts/run-codex-experiment.sh > "$BATCH_DIR/tlb.log" 2>&1 &
tlb_pid=$!
echo "$tlb_pid" > "$BATCH_DIR/tlb.pid"

RUN_ID="$PFR_RUN_ID" \
MODEL=deepseek-v4-pro \
TASK=proof \
INDICES="$PFR_INDICES" \
SAMPLES=1 \
CONCURRENCY="$CONCURRENCY_PER_DATASET" \
REASONING_EFFORT=high \
TMO=0 \
MAX_COMPILE_ATTEMPTS=10 \
CODEX_WRAPPER=run-logs/codex-gpt-custom \
SECRET_FILE=secret.txt \
SOURCE_SECRET=1 \
SUMMARY_DIR="run-logs/$PFR_RUN_ID" \
bash scripts/run-codex-experiment.sh > "$BATCH_DIR/pfr.log" 2>&1 &
pfr_pid=$!
echo "$pfr_pid" > "$BATCH_DIR/pfr.pid"

echo "tlb_pid=$tlb_pid pfr_pid=$pfr_pid"

tlb_status=0
pfr_status=0
wait "$tlb_pid" || tlb_status=$?
wait "$pfr_pid" || pfr_status=$?

{
  echo "# DeepSeek V4 Pro Unlimited Retry"
  echo
  echo "- Completed: $(date -Is)"
  echo "- TLB status: $tlb_status"
  echo "- PFR status: $pfr_status"
  echo
  if [[ -f "run-logs/$TLB_RUN_ID/summary.md" ]]; then
    echo "## TLB"
    echo
    sed -n '1,14p' "run-logs/$TLB_RUN_ID/summary.md"
    echo
  fi
  if [[ -f "run-logs/$PFR_RUN_ID/summary.md" ]]; then
    echo "## PFR"
    echo
    sed -n '1,14p' "run-logs/$PFR_RUN_ID/summary.md"
    echo
  fi
} > "$BATCH_DIR/summary.md"

echo "[$(date -Is)] workflow complete tlb=$tlb_status pfr=$pfr_status"
exit $(( tlb_status != 0 || pfr_status != 0 ))
