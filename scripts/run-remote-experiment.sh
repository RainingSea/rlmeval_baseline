#!/usr/bin/env bash
# 远程模型裸测入口: 标准 URL + API KEY 方式,默认非流式。
# 模型/端点/凭据统一走 MODEL_PROFILE(默认 relay-glm53:
#   glm-5.3 + secret.txt「内部中转」段 token.pjlab.org.cn);
# 生成/评分/summary 完全复用 run-direct-experiment.sh(track=direct_model)。
# 用法:
#   RUN_ID=xxx bash scripts/run-remote-experiment.sh
#   RUN_ID=xxx DIRECT_BG=1 bash scripts/run-remote-experiment.sh
# 可覆盖: MODEL_PROFILE(默认 relay-glm53)/MODEL/SECRET_SECTION/STREAM(默认 0=非流式)
#         TMO(默认 3600) MAX_TOKENS(默认不设) INDICES/SAMPLES/CONCURRENCY/TASK/DATASET
set -euo pipefail

cd "$(dirname "$0")/.."

# 凭据解析(SECRET_SECTION -> secret.txt)已收进 scripts/model-env.sh,
# 不再在入口脚本里 awk/sed secret.txt
export MODEL_PROFILE=${MODEL_PROFILE:-relay-glm53}
. scripts/model-env.sh

export MODEL
export STREAM=${STREAM-0}                   # 远程接口默认非流式
export TMO=${TMO-3600}
export MAX_TOKENS=${MAX_TOKENS-}

: "${RUN_ID:?Set RUN_ID, e.g. RUN_ID=remote-glm53-\$(date +%Y%m%d-%H%M%S)}"

exec bash scripts/run-direct-experiment.sh
