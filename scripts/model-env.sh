#!/usr/bin/env bash
# 统一的模型 profile 加载器(供各入口脚本 source,不要直接执行)。
#
# 入口脚本用法(cd 到仓库根目录后):
#   MODEL_PROFILE=${MODEL_PROFILE:-<默认>} ; . scripts/model-env.sh
#
# profile 文件位于 configs/profiles/<name>.env,一个文件描述「模型 × 端点 × 接入方式」
# 的组合。sglang 直连与 API 中转的差异不由脚本分支,而由 profile 字段承载:
#   FLAVOR           sglang(直连,无鉴权)| relay(API key 中转);元数据,便于日志自检
#   MODEL            模型名
#   BASE_URL/API_KEY 端点与凭据(sglang 直连写死占位 EMPTY;relay 通常不写,改配 SECRET_SECTION)
#   SECRET_SECTION   非空时从 secret.txt 的该段(## 标题)解析
#                    export OPENAI_API_KEY/OPENAI_BASE_URL='...' 补齐 API_KEY/BASE_URL
#   NO_PROXY_DOMAIN  需内网直连的域名,自动并入 NO_PROXY/no_proxy
#   NO_OUTPUT_SCHEMA STREAM REASONING_EFFORT  轨道参数默认值(codex/direct 轨道各取所需)
#
# 优先级:命令行环境变量 > profile 文件 > 入口脚本自身兜底默认。
# (profile 内一律用 ${VAR-default} 写法,外部已设置的变量不会被覆盖。)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "This file must be sourced: . scripts/model-env.sh" >&2
  exit 2
fi

_rlmeval_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${MODEL_PROFILE:?Set MODEL_PROFILE, e.g. MODEL_PROFILE=sglang-ds4pro (see configs/profiles/)}"

_profile="$_rlmeval_root/configs/profiles/$MODEL_PROFILE.env"
if [[ ! -f "$_profile" ]]; then
  echo "Unknown MODEL_PROFILE '$MODEL_PROFILE': $_profile not found; available:" >&2
  ls "$_rlmeval_root/configs/profiles" | sed 's/^/  /' >&2
  return 2
fi

# set -a: profile 里的赋值自动 export,入口脚本无需逐个 export
set -a
. "$_profile"
set +a

# relay 接入:从 secret.txt 指定段补齐凭据(解析逻辑与旧 run-remote-experiment.sh 一致)
if [[ -n "${SECRET_SECTION:-}" ]]; then
  _secret_file=${SECRET_FILE:-$_rlmeval_root/secret.txt}
  if [[ ! -f "$_secret_file" ]]; then
    echo "Secret file not found: $_secret_file" >&2
    return 2
  fi
  _picked=$(awk -v sec="$SECRET_SECTION" '
    $0 ~ "^## ?" sec { found = 1; next }
    /^## / { found = 0 }
    found { print }
  ' "$_secret_file")
  _sec_key=$(sed -n "s/^export OPENAI_API_KEY='\(.*\)'/\1/p" <<<"$_picked")
  _sec_url=$(sed -n "s/^export OPENAI_BASE_URL='\(.*\)'/\1/p" <<<"$_picked")
  if [[ -z "$_sec_key" || -z "$_sec_url" ]]; then
    echo "Section '$SECRET_SECTION' in $_secret_file lacks OPENAI_API_KEY/OPENAI_BASE_URL" >&2
    return 2
  fi
  export API_KEY=${API_KEY:-$_sec_key}
  export BASE_URL=${BASE_URL:-$_sec_url}
fi

export API_KEY=${API_KEY:-EMPTY}
# codex wrapper(codex-gpt-custom)吃 OPENAI_* 变量名
export OPENAI_API_KEY=${OPENAI_API_KEY:-$API_KEY}
export OPENAI_BASE_URL=${OPENAI_BASE_URL:-${BASE_URL%/}}

# 内网域名直连,兜底防止代理环境变量干扰;重复 source 不会重复追加
if [[ -n "${NO_PROXY_DOMAIN:-}" ]]; then
  case ",${NO_PROXY:-}," in
    *,"$NO_PROXY_DOMAIN",*) : ;;
    *)
      export NO_PROXY="${NO_PROXY:+${NO_PROXY},}$NO_PROXY_DOMAIN"
      export no_proxy="$NO_PROXY"
      ;;
  esac
fi

if [[ -z "${MODEL:-}" || -z "${BASE_URL:-}" ]]; then
  echo "MODEL_PROFILE '$MODEL_PROFILE' did not resolve MODEL/BASE_URL" >&2
  return 2
fi

unset _rlmeval_root _profile _secret_file _picked _sec_key _sec_url
