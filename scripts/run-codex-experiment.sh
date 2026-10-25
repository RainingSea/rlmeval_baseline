#!/usr/bin/env bash
set -u

cd /data/projects/math-harness-eval/RLMEval

: "${RUN_ID:?Set RUN_ID to a unique experiment identifier}"

# 模型/端点/凭据统一走 profile(见 scripts/model-env.sh 与 configs/profiles/);
# MODEL 等仍可环境变量覆盖,profile 只提供默认值
export MODEL_PROFILE=${MODEL_PROFILE:-relay-glm53}
. scripts/model-env.sh
MODEL=${MODEL:-glm-5.3}
TASK=${TASK:-proof}
INDICES=${INDICES:-168,41,38}
SAMPLES=${SAMPLES:-1}
CONCURRENCY=${CONCURRENCY:-4}
REASONING_EFFORT=${REASONING_EFFORT-high}
NO_OUTPUT_SCHEMA=${NO_OUTPUT_SCHEMA-0}
TMO=${TMO:-2400}
MAX_COMPILE_ATTEMPTS=${MAX_COMPILE_ATTEMPTS:-3}
DATASET=${DATASET:-data/rlm25_pfr_tlb.jsonl}
CODEX_WRAPPER=${CODEX_WRAPPER:-run-logs/codex-gpt-custom}
SECRET_FILE=${SECRET_FILE:-secret.txt}
SOURCE_SECRET=${SOURCE_SECRET:-1}
REBUILD_DATASET=${REBUILD_DATASET:-0}
SUMMARY_DIR=${SUMMARY_DIR:-run-logs/$RUN_ID}

export HARNESS_HOME=${HARNESS_HOME:-/data/projects/math-harness-eval/rlm-env/home}
export HOME="$HARNESS_HOME"
export XDG_CACHE_HOME=${XDG_CACHE_HOME:-$HARNESS_HOME/.cache}
export ELAN_HOME=${ELAN_HOME:-/data/projects/math-harness-eval/elan}
export CODEX_BIN=${CODEX_BIN:-/usr/local/bin/codex}
export PATH="$ELAN_HOME/bin:$PATH"

# profile 已提供凭据(OPENAI_API_KEY 非空)时跳过整文件 source,
# 避免 secret.txt 两个中转段的 export 覆盖 profile 选定的段
if [[ "$SOURCE_SECRET" == "1" && -z "${OPENAI_API_KEY:-}" ]]; then
  if [[ ! -f "$SECRET_FILE" ]]; then
    echo "Secret file not found: $SECRET_FILE" >&2
    exit 2
  fi
  set -a
  source "$SECRET_FILE"
  set +a
fi

if [[ "$REBUILD_DATASET" == "1" || ! -f "$DATASET" ]]; then
  ./rlmv-eval items \
    --config configs/benchmark/pfr_tlb.yaml \
    --out "$DATASET" \
    --project-map "PFR=/data/projects/math-harness-eval/rlm-env/pfr,TLB=/data/projects/math-harness-eval/rlm-env/tlb"
fi

if [[ -e "artifacts/$RUN_ID/generations.jsonl" ]]; then
  echo "Run ID already exists: artifacts/$RUN_ID/generations.jsonl" >&2
  exit 3
fi

mkdir -p "$SUMMARY_DIR"
cat > "$SUMMARY_DIR/config.txt" <<EOF
RUN_ID=$RUN_ID
MODEL=$MODEL
MODEL_PROFILE=$MODEL_PROFILE
TASK=$TASK
INDICES=$INDICES
SAMPLES=$SAMPLES
CONCURRENCY=$CONCURRENCY
REASONING_EFFORT=$REASONING_EFFORT
NO_OUTPUT_SCHEMA=$NO_OUTPUT_SCHEMA
TMO=$TMO
MAX_COMPILE_ATTEMPTS=$MAX_COMPILE_ATTEMPTS
DATASET=$DATASET
CODEX_WRAPPER=$CODEX_WRAPPER
SECRET_FILE=$SECRET_FILE
EOF

echo "[$(date -Is)] generation start"
echo "run_id=$RUN_ID model=$MODEL task=$TASK samples=$SAMPLES concurrency=$CONCURRENCY"
echo "indices=$INDICES"

generation_status=0
schema_args=()
if [[ "$NO_OUTPUT_SCHEMA" == "1" ]]; then
  schema_args=(--no-output-schema)
fi
./rlmv-eval run-codex \
  --model "$MODEL" \
  --dataset "$DATASET" \
  --indices "$INDICES" \
  --samples "$SAMPLES" \
  --concurrency "$CONCURRENCY" \
  --timeout-seconds "$TMO" \
  --max-compile-attempts "$MAX_COMPILE_ATTEMPTS" \
  --reasoning-effort "$REASONING_EFFORT" \
  "${schema_args[@]}" \
  --task "$TASK" \
  --artifacts-dir artifacts \
  --workspaces-dir agent_workspaces \
  --codex-bin "$CODEX_WRAPPER" \
  --elan-home "$ELAN_HOME" \
  --cache-dir .rlm-cache \
  --run-id "$RUN_ID" || generation_status=$?

score_status=0
if [[ -f "artifacts/$RUN_ID/generations.jsonl" ]]; then
  echo "[$(date -Is)] scoring start"
  ./rlmv-eval score \
    --dataset "$DATASET" \
    --input "artifacts/$RUN_ID/generations.jsonl" \
    --output "artifacts/$RUN_ID/scores.jsonl" \
    --task "$TASK" || score_status=$?
else
  score_status=4
  echo "No generations.jsonl was produced; scoring skipped" >&2
fi

summary_status=0
/root/miniconda3/envs/rlmeval/bin/python scripts/summarize_codex_run.py \
  --run-id "$RUN_ID" \
  --dataset "$DATASET" \
  --output-dir "$SUMMARY_DIR" \
  --expected-samples "$SAMPLES" || summary_status=$?

echo "[$(date -Is)] experiment complete generation=$generation_status score=$score_status summary=$summary_status"
if (( generation_status != 0 )); then
  exit "$generation_status"
fi
if (( score_status != 0 )); then
  exit "$score_status"
fi
exit "$summary_status"
