#!/usr/bin/env bash
# 顺序全量裸模型评测:PFR 全部题 → 完成后 TLB 全部题(前台逐阶段,本身放在后台跑)。
# 远程中转 glm-5.3,pass@1(SAMPLES=1),并发 6,流式(非流式经中转会挂死,勿改)。
# 单题失败/超时只记 status,不中断批次。用法:
#   setsid nohup bash scripts/run-remote-full-sequential.sh > run-logs/<id>/batch.log 2>&1 &
set -euo pipefail

cd /data/projects/math-harness-eval/RLMEval

BATCH_ID=${BATCH_ID:-glm53-remote-full-$(date +%Y%m%d-%H%M%S)}
BATCH_DIR=run-logs/$BATCH_ID
DATASET=${DATASET:-data/rlm25_pfr_tlb.jsonl}
CONCURRENCY=${CONCURRENCY:-6}
TMO=${TMO:-3600}

mkdir -p "$BATCH_DIR"
echo "$$" > "$BATCH_DIR/batch.pid"

PY=/root/miniconda3/envs/rlmeval/bin/python
# 支持外部覆盖索引(如续跑剩余题): PFR_INDICES / TLB_INDICES
PFR_INDICES=${PFR_INDICES:-$($PY -c "
import json
print(','.join(str(r['index']) for r in map(json.loads, open('$DATASET')) if r['repo']=='PFR'))")}
TLB_INDICES=${TLB_INDICES:-$($PY -c "
import json
print(','.join(str(r['index']) for r in map(json.loads, open('$DATASET')) if r['repo']=='TLB'))")}

{
  echo "batch_id=$BATCH_ID"
  echo "pfr_items=$(tr ',' '\n' <<<"$PFR_INDICES" | grep -c .)"
  echo "tlb_items=$(tr ',' '\n' <<<"$TLB_INDICES" | grep -c .)"
  echo "concurrency=$CONCURRENCY tmo=$TMO model=glm-5.3 stream=1 samples=1"
} | tee "$BATCH_DIR/config.txt"

for phase in PFR TLB; do
  case $phase in
    PFR) indices=$PFR_INDICES ;;
    TLB) indices=$TLB_INDICES ;;
  esac
  echo "[$(date -Is)] phase $phase start: $(tr ',' '\n' <<<"$indices" | grep -c .) items"
  status=0
  RUN_ID=$BATCH_ID-$phase \
  INDICES=$indices \
  SAMPLES=1 \
  CONCURRENCY=$CONCURRENCY \
  TMO=$TMO \
  STREAM=1 \
  MODEL=glm-5.3 \
  bash scripts/run-remote-experiment.sh \
    > "$BATCH_DIR/$phase.log" 2>&1 || status=$?
  echo "[$(date -Is)] phase $phase done (exit=$status)"
done

echo "[$(date -Is)] batch complete"
