#!/usr/bin/env bash
set -euo pipefail

cd /data/projects/math-harness-eval/RLMEval

: "${RUN_ID:?Set RUN_ID to the existing experiment run ID}"

DATASET=${DATASET:-data/rlm25_pfr_tlb.jsonl}
TASK=${TASK:-proof}
EXPECTED_SAMPLES=${EXPECTED_SAMPLES:-1}
MAX_ATTEMPTS=${MAX_ATTEMPTS:-2}
ARTIFACT_DIR=${ARTIFACT_DIR:-artifacts/$RUN_ID}
SUMMARY_DIR=${SUMMARY_DIR:-run-logs/$RUN_ID}

GENERATIONS="$ARTIFACT_DIR/generations.jsonl"
CANONICAL_SCORES="$ARTIFACT_DIR/scores.jsonl"
VERIFIED_MARKER="$SUMMARY_DIR/rescore-verified.json"
SKIP_IF_VERIFIED=${SKIP_IF_VERIFIED:-1}

if [[ "$SKIP_IF_VERIFIED" == "1" && -f "$VERIFIED_MARKER" && -f "$CANONICAL_SCORES" ]]; then
  echo "[$(date -Is)] verified rescore already exists; skipping: $RUN_ID"
  echo "marker=$VERIFIED_MARKER"
  exit 0
fi

if [[ ! -f "$GENERATIONS" ]]; then
  echo "Missing generations file: $GENERATIONS" >&2
  exit 2
fi

export HARNESS_HOME=${HARNESS_HOME:-/data/projects/math-harness-eval/rlm-env/home}
export HOME="$HARNESS_HOME"
export XDG_CACHE_HOME=${XDG_CACHE_HOME:-$HARNESS_HOME/.cache}
export ELAN_HOME=${ELAN_HOME:-/data/projects/math-harness-eval/elan}
export PATH="$ELAN_HOME/bin:$PATH"

mkdir -p "$SUMMARY_DIR"

selected_scores=""
for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  stamp=$(date +%Y%m%d-%H%M%S)
  candidate_scores="$ARTIFACT_DIR/scores.rescore-$stamp-attempt$attempt.jsonl"
  echo "[$(date -Is)] rescore attempt $attempt/$MAX_ATTEMPTS: $RUN_ID"

  ./rlmv-eval score \
    --dataset "$DATASET" \
    --input "$GENERATIONS" \
    --output "$candidate_scores" \
    --task "$TASK"

  if /root/miniconda3/envs/rlmeval/bin/python - "$GENERATIONS" "$candidate_scores" <<'PY'
import collections
import json
import sys

generation_path, score_path = sys.argv[1:]
generations = [json.loads(line) for line in open(generation_path, encoding="utf-8") if line.strip()]
scores = [json.loads(line) for line in open(score_path, encoding="utf-8") if line.strip()]
counts = collections.Counter(row.get("score_status") for row in scores)
print(f"generated={len(generations)} scored={len(scores)} score_statuses={dict(counts)}")
if len(scores) != len(generations):
    raise SystemExit(1)
if counts.get("checker_error", 0):
    raise SystemExit(1)
PY
  then
    selected_scores="$candidate_scores"
    break
  fi

  echo "[$(date -Is)] rescore validation failed; retrying with a fresh Lean server" >&2
done

if [[ -z "$selected_scores" ]]; then
  echo "No valid score file produced after $MAX_ATTEMPTS attempts" >&2
  exit 3
fi

backup_stamp=$(date +%Y%m%d-%H%M%S)
if [[ -f "$CANONICAL_SCORES" ]]; then
  cp "$CANONICAL_SCORES" "$ARTIFACT_DIR/scores.before-rescore-$backup_stamp.jsonl"
fi
if [[ -f "$SUMMARY_DIR/summary.json" ]]; then
  cp "$SUMMARY_DIR/summary.json" "$SUMMARY_DIR/summary.before-rescore-$backup_stamp.json"
fi
if [[ -f "$SUMMARY_DIR/summary.md" ]]; then
  cp "$SUMMARY_DIR/summary.md" "$SUMMARY_DIR/summary.before-rescore-$backup_stamp.md"
fi

cp "$selected_scores" "$CANONICAL_SCORES"

/root/miniconda3/envs/rlmeval/bin/python scripts/summarize_codex_run.py \
  --run-id "$RUN_ID" \
  --dataset "$DATASET" \
  --output-dir "$SUMMARY_DIR" \
  --expected-samples "$EXPECTED_SAMPLES"

/root/miniconda3/envs/rlmeval/bin/python - "$RUN_ID" "$CANONICAL_SCORES" "$VERIFIED_MARKER" <<'PYMARKER'
import collections
import datetime
import json
import sys

run_id, score_path, marker_path = sys.argv[1:]
scores = [json.loads(line) for line in open(score_path, encoding="utf-8") if line.strip()]
marker = {
    "run_id": run_id,
    "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "scores": score_path,
    "score_statuses": dict(collections.Counter(row.get("score_status") for row in scores)),
}
open(marker_path, "w", encoding="utf-8").write(json.dumps(marker, ensure_ascii=False, indent=2) + "\n")
PYMARKER

echo "[$(date -Is)] canonical rescore complete: $RUN_ID"
echo "scores=$CANONICAL_SCORES"
echo "summary=$SUMMARY_DIR/summary.md"
