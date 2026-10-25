#!/usr/bin/env bash
# 直连本地 sglang(OpenAI 兼容 Responses API)跑 Codex harness 实验。
# 取代旧的 codex-ds-internal wrapper + 127.0.0.1:4102 清洗代理:
#   - codex-cli >= 0.163 已容忍 sglang SSE 里的浮点时间戳
#   - 新端点原生支持 reasoning 参数与 reasoning.* include(2026-10-19 实测)
# 用法:
#   RUN_ID=xxx bash scripts/run-sglang-experiment.sh              # 前台
#   RUN_ID=xxx SGLANG_BG=1 bash scripts/run-sglang-experiment.sh  # 后台
# 其余参数(INDICES/SAMPLES/CONCURRENCY/TMO/REASONING_EFFORT/...)
# 见 scripts/run-codex-experiment.sh,均可通过环境变量覆盖。
set -euo pipefail

cd "$(dirname "$0")/.."

# 模型/端点/凭据统一走 profile(见 scripts/model-env.sh 与 configs/profiles/):
# 默认 sglang 直连 DeepSeek-V4-Pro;换模型/端点用 MODEL_PROFILE=relay-glm53 等,
# 单项仍可用 MODEL/BASE_URL/OPENAI_API_KEY 等环境变量覆盖。
export MODEL_PROFILE=${MODEL_PROFILE:-sglang-ds4pro}
. scripts/model-env.sh

export SGLANG_BASE_URL=${SGLANG_BASE_URL:-$BASE_URL}
export MODEL

# 通用 wrapper 只做 env -> codex --config 映射,provider 由 profile 提供的
# OPENAI_BASE_URL/OPENAI_API_KEY 决定(model-env.sh 已按 profile export)
export CODEX_WRAPPER=${CODEX_WRAPPER:-run-logs/codex-gpt-custom}
export SOURCE_SECRET=${SOURCE_SECRET:-0}          # 凭据已由 profile 提供,不整文件 source secret.txt
# sglang 会把 Responses text.format 的 json_schema 约束施加到整个生成上,
# 直接杀死工具调用(2026-10-23 实测),因此默认不发 --output-schema
# (sglang 类 profile 已默认 1,此处保留兜底);
# 最终 JSON 约定已写死在 agent prompt 里,评分只看 Candidate.lean。
export NO_OUTPUT_SCHEMA=${NO_OUTPUT_SCHEMA-1}

: "${RUN_ID:?Set RUN_ID, e.g. RUN_ID=smoke-sglang-\$(date +%Y%m%d-%H%M%S)}"

if [[ "${SGLANG_BG:-0}" == "1" ]]; then
  exec bash scripts/start-codex-experiment-background.sh
fi
exec bash scripts/run-codex-experiment.sh
