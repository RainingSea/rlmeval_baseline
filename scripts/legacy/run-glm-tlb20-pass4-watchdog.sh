#!/usr/bin/env bash
set -u

cd /data/projects/math-harness-eval/RLMEval

SMOKE_RUN_ID=${SMOKE_RUN_ID:-verify-glm-pass16-high-c8}
RUN_ID=${RUN_ID:-glm-tlb20-pass4-20261017}
LOG_DIR=${LOG_DIR:-run-logs/$RUN_ID}
SMOKE_SCORES="artifacts/$SMOKE_RUN_ID/scores.jsonl"
DATASET=data/rlm25_pfr_tlb.jsonl
EXPECTED_SMOKE_SCORES=48
WAIT_TIMEOUT_SECONDS=${WAIT_TIMEOUT_SECONDS:-28800}

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/watchdog.log") 2>&1

echo "[$(date -Is)] watchdog start"
echo "smoke_run_id=$SMOKE_RUN_ID"
echo "target_run_id=$RUN_ID"
echo "target_dataset=TLB target_items=20 samples_per_item=4 concurrency=4"

deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
while true; do
  score_count=0
  if [[ -f "$SMOKE_SCORES" ]]; then
    score_count=$(wc -l < "$SMOKE_SCORES")
  fi
  if (( score_count >= EXPECTED_SMOKE_SCORES )); then
    break
  fi
  if (( SECONDS >= deadline )); then
    echo "[$(date -Is)] abort: timed out waiting for $EXPECTED_SMOKE_SCORES smoke scores; found $score_count"
    exit 2
  fi
  if ! pgrep -f "rlm_agent.cli score.*$SMOKE_RUN_ID" >/dev/null \
      && [[ -f "artifacts/$SMOKE_RUN_ID/generations.jsonl" ]] \
      && (( score_count > 0 )); then
    echo "[$(date -Is)] abort: smoke scorer stopped early at $score_count/$EXPECTED_SMOKE_SCORES"
    exit 3
  fi
  echo "[$(date -Is)] waiting for smoke scores: $score_count/$EXPECTED_SMOKE_SCORES"
  sleep 30
done

if ! /root/miniconda3/envs/rlmeval/bin/python - "$SMOKE_SCORES" "$LOG_DIR/smoke-summary.json" <<'PY'
import json
import sys
from collections import defaultdict
from pathlib import Path

scores_path = Path(sys.argv[1])
summary_path = Path(sys.argv[2])
by_item = defaultdict(list)
for line in scores_path.read_text().splitlines():
    row = json.loads(line)
    by_item[int(row["item_index"])].append(row)

items = {}
solved = 0
for index in (38, 41, 168):
    rows = by_item[index]
    passed = sum(row.get("proof_ok") is True for row in rows)
    items[str(index)] = {
        "samples": len(rows),
        "passed": passed,
        "pass_at_16": passed > 0,
    }
    solved += passed > 0

summary = {
    "criterion": "at least 2 of 3 smoke items have one or more passing samples",
    "solved_items": solved,
    "success": solved >= 2,
    "items": items,
}
summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
print(json.dumps(summary, ensure_ascii=False))
raise SystemExit(0 if summary["success"] else 1)
PY
then
  echo "[$(date -Is)] smoke gate failed; target run will not start"
  exit 4
fi

/root/miniconda3/envs/rlmeval/bin/python - "$DATASET" "$LOG_DIR" <<'PY'
import json
import random
import sys
from pathlib import Path

dataset_path = Path(sys.argv[1])
log_dir = Path(sys.argv[2])
items = [json.loads(line) for line in dataset_path.read_text().splitlines()]
candidates = [item for item in items if item["project_name"] == "TLB" and int(item["index"]) != 168]
selected = random.Random(20261017).sample(candidates, 20)
selected.sort(key=lambda item: int(item["index"]))

manifest = [
    {
        "index": int(item["index"]),
        "name": item["name"],
        "project_name": item["project_name"],
        "file": item["file"],
    }
    for item in selected
]
(log_dir / "selection.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
(log_dir / "indices.txt").write_text(",".join(str(item["index"]) for item in manifest) + "\n")
with (log_dir / "selection.tsv").open("w") as handle:
    handle.write("index\tname\tproject\tfile\n")
    for item in manifest:
        handle.write(f'{item["index"]}\t{item["name"]}\t{item["project_name"]}\t{item["file"]}\n')
print("selected_indices=" + ",".join(str(item["index"]) for item in manifest))
PY

if [[ -e "artifacts/$RUN_ID/generations.jsonl" ]]; then
  echo "[$(date -Is)] abort: artifacts/$RUN_ID/generations.jsonl already exists"
  exit 5
fi

set -a
source secret.txt
set +a
export ELAN_HOME=/data/projects/math-harness-eval/elan
export CODEX_BIN=/usr/local/bin/codex

INDICES=$(cat "$LOG_DIR/indices.txt")
echo "[$(date -Is)] target generation start"
set +e
TASK=proof \
MODEL=glm-5.3 \
CODEX_WRAPPER=run-logs/codex-gpt-custom \
REASONING_EFFORT=high \
INDICES="$INDICES" \
SAMPLES=4 \
CONCURRENCY=4 \
TMO=2400 \
RUN_ID="$RUN_ID" \
bash scripts/run-glm-smoke.sh
run_status=$?
set -e

/root/miniconda3/envs/rlmeval/bin/python - "$RUN_ID" "$LOG_DIR" "$run_status" <<'PY'
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

run_id = sys.argv[1]
log_dir = Path(sys.argv[2])
run_status = int(sys.argv[3])
selection = json.loads((log_dir / "selection.json").read_text())
generations_path = Path("artifacts") / run_id / "generations.jsonl"
scores_path = Path("artifacts") / run_id / "scores.jsonl"

generations = []
if generations_path.exists():
    generations = [json.loads(line) for line in generations_path.read_text().splitlines()]
scores = []
if scores_path.exists():
    scores = [json.loads(line) for line in scores_path.read_text().splitlines()]

generation_by_item = defaultdict(list)
for row in generations:
    generation_by_item[int(row["item_index"])].append(row)
scores_by_item = defaultdict(list)
for row in scores:
    scores_by_item[int(row["item_index"])].append(row)

summary_items = []
for item in selection:
    index = int(item["index"])
    item_generations = generation_by_item[index]
    item_scores = scores_by_item[index]
    passed = sum(row.get("proof_ok") is True for row in item_scores)
    summary_items.append({
        **item,
        "generated_samples": len(item_generations),
        "generation_statuses": dict(Counter(row.get("status", "missing") for row in item_generations)),
        "scored_samples": len(item_scores),
        "score_statuses": dict(Counter(row.get("score_status", "missing") for row in item_scores)),
        "passed_samples": passed,
        "pass_at_4": passed > 0,
    })

solved = sum(item["pass_at_4"] for item in summary_items)
summary = {
    "run_id": run_id,
    "model": "glm-5.3",
    "dataset": "TLB",
    "task": "proof",
    "samples_per_item": 4,
    "concurrency": 4,
    "selected_items": len(selection),
    "generated_samples": len(generations),
    "scored_samples": len(scores),
    "solved_items": solved,
    "pass_at_4_rate": solved / len(selection) if selection else 0,
    "command_exit_status": run_status,
    "items": summary_items,
}
(log_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")

lines = [
    f"# {run_id}",
    "",
    f"- Model: `glm-5.3`",
    f"- Dataset: `TLB`",
    f"- Task: `proof`",
    f"- Configuration: 20 items × 4 samples, concurrency 4",
    f"- Generated samples: {len(generations)}/80",
    f"- Scored samples: {len(scores)}/80",
    f"- Solved items (Pass@4): {solved}/20",
    f"- Command exit status: {run_status}",
    "",
    "| Index | Item | Generated | Scored | Passed | Pass@4 | Score statuses |",
    "|---:|---|---:|---:|---:|:---:|---|",
]
for item in summary_items:
    statuses = ", ".join(f"{key}={value}" for key, value in sorted(item["score_statuses"].items())) or "none"
    lines.append(
        f'| {item["index"]} | {item["name"]} | {item["generated_samples"]} | '
        f'{item["scored_samples"]} | {item["passed_samples"]} | '
        f'{"yes" if item["pass_at_4"] else "no"} | {statuses} |'
    )
(log_dir / "summary.md").write_text("\n".join(lines) + "\n")
print(f"summary_written={log_dir / 'summary.md'} solved={solved}/20")
PY

echo "[$(date -Is)] watchdog complete with target exit status $run_status"
exit "$run_status"
