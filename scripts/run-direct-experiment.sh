#!/usr/bin/env bash
# 裸模型单发评测(不经 codex harness):
#   - 复用给 codex 的同一条 agent 提示词,workspace 文件内联进 prompt
#   - 每个样本只调一次 chat/completions,无工具、无编译循环
#   - 评分(typecheck+BEq+)与 summary 流程和 codex 轨道完全一致(track=direct_model)
# 用法:
#   RUN_ID=xxx bash scripts/run-direct-experiment.sh                 # 前台
#   RUN_ID=xxx DIRECT_BG=1 bash scripts/run-direct-experiment.sh     # 后台
# 可覆盖: MODEL_PROFILE(默认 sglang-ds4pro,模型/端点/凭据统一入口)/MODEL/BASE_URL/INDICES/SAMPLES/CONCURRENCY/TMO/MAX_TOKENS(默认不设)/TASK/DATASET
set -euo pipefail

cd "$(dirname "$0")/.."

: "${RUN_ID:?Set RUN_ID to a unique experiment identifier}"

# 模型/端点/凭据统一走 profile(见 scripts/model-env.sh 与 configs/profiles/);
# 默认 sglang 直连 DeepSeek-V4-Pro,API 中转模型用 MODEL_PROFILE=relay-glm53 等
export MODEL_PROFILE=${MODEL_PROFILE:-sglang-ds4pro}
. scripts/model-env.sh
TASK=${TASK:-proof}
INDICES=${INDICES:-161}
SAMPLES=${SAMPLES:-1}
CONCURRENCY=${CONCURRENCY:-4}
TMO=${TMO:-3600}
MAX_TOKENS=${MAX_TOKENS-}
REASONING_EFFORT=${REASONING_EFFORT-high}
STREAM=${STREAM-1}
DATASET=${DATASET:-data/rlm25_pfr_tlb.jsonl}
REBUILD_DATASET=${REBUILD_DATASET:-0}
SUMMARY_DIR=${SUMMARY_DIR:-run-logs/$RUN_ID}

export HARNESS_HOME=${HARNESS_HOME:-/data/projects/math-harness-eval/rlm-env/home}
export HOME="$HARNESS_HOME"
export XDG_CACHE_HOME=${XDG_CACHE_HOME:-$HARNESS_HOME/.cache}
export ELAN_HOME=${ELAN_HOME:-/data/projects/math-harness-eval/elan}
# NO_PROXY 由 model-env.sh 按 profile 的 NO_PROXY_DOMAIN 统一处理

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
TRACK=direct_model
MODEL=$MODEL
MODEL_PROFILE=$MODEL_PROFILE
BASE_URL=$BASE_URL
TASK=$TASK
INDICES=$INDICES
SAMPLES=$SAMPLES
CONCURRENCY=$CONCURRENCY
TMO=$TMO
MAX_TOKENS=${MAX_TOKENS:-unset}
REASONING_EFFORT=$REASONING_EFFORT
STREAM=$STREAM
DATASET=$DATASET
EOF

run_pipeline() {
  echo "[$(date -Is)] generation start (direct, single-shot)"
  echo "run_id=$RUN_ID model=$MODEL task=$TASK samples=$SAMPLES concurrency=$CONCURRENCY max_tokens=$MAX_TOKENS"
  echo "indices=$INDICES base_url=$BASE_URL"

  generation_status=0
  max_tokens_args=()
  if [[ -n "$MAX_TOKENS" ]]; then
    max_tokens_args=(--max-tokens "$MAX_TOKENS")
  fi
  stream_args=()
  if [[ "$STREAM" != "1" ]]; then
    stream_args=(--no-stream)
  fi
  OPENAI_API_KEY="$API_KEY" ./rlmv-eval run-direct \
    --model "$MODEL" \
    --base-url "$BASE_URL" \
    "${max_tokens_args[@]}" \
    "${stream_args[@]}" \
    --reasoning-effort "$REASONING_EFFORT" \
    --dataset "$DATASET" \
    --indices "$INDICES" \
    --samples "$SAMPLES" \
    --concurrency "$CONCURRENCY" \
    --timeout-seconds "$TMO" \
    --task "$TASK" \
    --artifacts-dir artifacts \
    --workspaces-dir agent_workspaces \
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
}

if [[ "${DIRECT_BG:-0}" == "1" ]]; then
  DIRECT_BG=0 setsid nohup bash "$0" \
    > "$SUMMARY_DIR/background.log" 2>&1 < /dev/null &
  background_pid=$!
  echo "$background_pid" > "$SUMMARY_DIR/background.pid"
  echo "background_pid=$background_pid"
  echo "log=$SUMMARY_DIR/background.log"
  echo "summary=$SUMMARY_DIR/summary.md"
else
  run_pipeline
fi
