#!/usr/bin/env bash
set -euo pipefail

cd /data/projects/math-harness-eval/RLMEval

: "${RUN_ID:?Set RUN_ID before starting a background experiment}"

LOG_DIR=${SUMMARY_DIR:-run-logs/$RUN_ID}
mkdir -p "$LOG_DIR"

if [[ -f "$LOG_DIR/background.pid" ]]; then
  old_pid=$(cat "$LOG_DIR/background.pid")
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "A background process is already running for $RUN_ID: PID $old_pid" >&2
    exit 2
  fi
fi
if [[ -e "artifacts/$RUN_ID/generations.jsonl" ]]; then
  echo "Run ID already exists: artifacts/$RUN_ID/generations.jsonl" >&2
  exit 3
fi

export RUN_ID
export MODEL_PROFILE=${MODEL_PROFILE:-relay-glm53}
export MODEL=${MODEL:-glm-5.3}
export TASK=${TASK:-proof}
export INDICES=${INDICES:-168,41,38}
export SAMPLES=${SAMPLES:-1}
export CONCURRENCY=${CONCURRENCY:-4}
export REASONING_EFFORT=${REASONING_EFFORT-high}
export TMO=${TMO:-2400}
export MAX_COMPILE_ATTEMPTS=${MAX_COMPILE_ATTEMPTS:-3}
export DATASET=${DATASET:-data/rlm25_pfr_tlb.jsonl}
export CODEX_WRAPPER=${CODEX_WRAPPER:-run-logs/codex-gpt-custom}
export SECRET_FILE=${SECRET_FILE:-secret.txt}
export SOURCE_SECRET=${SOURCE_SECRET:-1}
export REBUILD_DATASET=${REBUILD_DATASET:-0}
export SUMMARY_DIR=$LOG_DIR

setsid nohup bash scripts/run-codex-experiment.sh > "$LOG_DIR/background.log" 2>&1 < /dev/null &
background_pid=$!
echo "$background_pid" > "$LOG_DIR/background.pid"

cat > "$LOG_DIR/launch.txt" <<EOF
started_at=$(date -Is)
pid=$background_pid
RUN_ID=$RUN_ID
MODEL=$MODEL
MODEL_PROFILE=$MODEL_PROFILE
TASK=$TASK
INDICES=$INDICES
SAMPLES=$SAMPLES
CONCURRENCY=$CONCURRENCY
REASONING_EFFORT=$REASONING_EFFORT
TMO=$TMO
DATASET=$DATASET
CODEX_WRAPPER=$CODEX_WRAPPER
SECRET_FILE=$SECRET_FILE
EOF

echo "background_pid=$background_pid"
echo "log=$LOG_DIR/background.log"
echo "summary=$LOG_DIR/summary.md"
