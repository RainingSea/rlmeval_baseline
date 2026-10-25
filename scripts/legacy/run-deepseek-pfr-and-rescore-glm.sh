#!/usr/bin/env bash
set -euo pipefail

cd /data/projects/math-harness-eval/RLMEval

DEEPSEEK_RUN_ID=${DEEPSEEK_RUN_ID:-deepseek-v4-pro-pfr145-easy-pass1-$(date +%Y%m%d-%H%M%S)}
DEEPSEEK_CONCURRENCY=${DEEPSEEK_CONCURRENCY:-3}
DEEPSEEK_TIMEOUT=${DEEPSEEK_TIMEOUT:-2400}
WORKFLOW_DIR=${WORKFLOW_DIR:-run-logs/$DEEPSEEK_RUN_ID}
PFR_INDICES=$(cat run-logs/selections/pfr-all/indices.txt)

mkdir -p "$WORKFLOW_DIR"

cat > "$WORKFLOW_DIR/workflow-config.txt" <<CONFIG
DEEPSEEK_RUN_ID=$DEEPSEEK_RUN_ID
MODEL=deepseek-v4-pro
TASK=proof
ITEMS=145
SAMPLES=1
CONCURRENCY=$DEEPSEEK_CONCURRENCY
REASONING_EFFORT=high
TMO=$DEEPSEEK_TIMEOUT
GLM_TLB_RUN_ID=glm53-tlb124-easy-pass1-20261017-114645
GLM_PFR_RUN_ID=glm53-pfr145-easy-pass1-20261017-143909
CONFIG

echo "[$(date -Is)] DeepSeek PFR generation start: $DEEPSEEK_RUN_ID"
RUN_ID="$DEEPSEEK_RUN_ID" \
MODEL=deepseek-v4-pro \
TASK=proof \
INDICES="$PFR_INDICES" \
SAMPLES=1 \
CONCURRENCY="$DEEPSEEK_CONCURRENCY" \
REASONING_EFFORT=high \
TMO="$DEEPSEEK_TIMEOUT" \
MAX_COMPILE_ATTEMPTS=3 \
CODEX_WRAPPER=run-logs/codex-gpt-custom \
SECRET_FILE=secret.txt \
SOURCE_SECRET=1 \
SUMMARY_DIR="$WORKFLOW_DIR" \
bash scripts/run-codex-experiment.sh

echo "[$(date -Is)] DeepSeek PFR verified rescore start"
RUN_ID="$DEEPSEEK_RUN_ID" EXPECTED_SAMPLES=1 bash scripts/rescore-codex-run.sh

echo "[$(date -Is)] GLM TLB verified rescore start"
RUN_ID=glm53-tlb124-easy-pass1-20261017-114645 EXPECTED_SAMPLES=1 bash scripts/rescore-codex-run.sh

echo "[$(date -Is)] GLM PFR verified rescore start"
RUN_ID=glm53-pfr145-easy-pass1-20261017-143909 EXPECTED_SAMPLES=1 bash scripts/rescore-codex-run.sh

{
  echo "# DeepSeek PFR and GLM Rescore Workflow"
  echo
  echo "- Completed: $(date -Is)"
  echo "- DeepSeek PFR run: \`$DEEPSEEK_RUN_ID\`"
  echo "- GLM TLB run: \`glm53-tlb124-easy-pass1-20261017-114645\`"
  echo "- GLM PFR run: \`glm53-pfr145-easy-pass1-20261017-143909\`"
  echo
  for summary in "$WORKFLOW_DIR/summary.md" \
    run-logs/glm53-tlb124-easy-pass1-20261017-114645/summary.md \
    run-logs/glm53-pfr145-easy-pass1-20261017-143909/summary.md; do
    echo "## $summary"
    echo
    sed -n '1,12p' "$summary"
    echo
  done
} > "$WORKFLOW_DIR/workflow-summary.md"

echo "[$(date -Is)] workflow complete"
echo "workflow_summary=$WORKFLOW_DIR/workflow-summary.md"
