# RLMEval 实验运行手册

> 最后更新：2026-10-17  
> 工作目录：`/data/projects/math-harness-eval/RLMEval`

本文档说明如何在当前环境中使用 RLMEval 数据集和 Codex harness 运行：

- 小规模 smoke test；
- Pass@k 测试；
- 固定随机子集实验；
- PFR、TLB 或完整 269 题实验；
- GLM、GPT、自定义 Responses API 和 DS wrapper；
- 前台运行与可断线的后台运行；
- 从 `generations.jsonl` / `scores.jsonl` 重新统计结果；
- 常见失败的诊断和恢复方式。

本文档优先使用新增的通用脚本，不建议为每个模型复制一份新的长 shell 脚本。

---

## 1. 当前数据和环境

### 1.1 数据集

当前合并数据集：

```text
data/rlm25_pfr_tlb.jsonl
```

题目数量：

| 项目 | 题数 |
|---|---:|
| PFR | 145 |
| TLB | 124 |
| 总计 | 269 |

题目索引范围为 `1..269`。运行时使用的是数据集中的 `index` 字段，而不是 JSONL 的零基行号。

### 1.2 Conda、Lean 和 Codex

当前约定：

```text
Conda 环境: /root/miniconda3/envs/rlmeval
Elan:       /data/projects/math-harness-eval/elan
Codex CLI:  /usr/local/bin/codex
项目目录:   /data/projects/math-harness-eval/RLMEval
```

通用 runner 会自动设置：

```bash
HOME=/data/projects/math-harness-eval/rlm-env/home
XDG_CACHE_HOME=/data/projects/math-harness-eval/rlm-env/home/.cache
ELAN_HOME=/data/projects/math-harness-eval/elan
PATH="$ELAN_HOME/bin:$PATH"
```

这些设置用于避免HOME目录只读、Lean 缓存位置错误和评分阶段找不到 `lake`。

### 1.3 快速自检

```bash
cd /data/projects/math-harness-eval/RLMEval

/root/miniconda3/envs/rlmeval/bin/python --version
/usr/local/bin/codex --version
test -x /data/projects/math-harness-eval/elan/bin/lake
wc -l data/rlm25_pfr_tlb.jsonl
```

最后一条应输出：

```text
269 data/rlm25_pfr_tlb.jsonl
```

---

## 2. 整体执行链路

本手册中的实验不是“只向模型发送一段 prompt”。完整链路是：

```text
RLMEval 数据集
  → rlmv-eval run-codex
  → Codex CLI harness
  → 自定义 Responses API
  → 目标模型
  → 模型请求 shell / 文件编辑工具
  → Codex 在独立 workspace 中执行工具
  → check_candidate.sh 做任务内 Lean 检查
  → rlmv-eval score 做独立正式评分
  → generations.jsonl + scores.jsonl
  → summarize_codex_run.py 生成 summary.md/json
```

模型负责推理和决定何时调用工具；Codex harness 负责：

- 创建独立任务 workspace；
- 提供 `TASK.md`、`Context.lean` 和 `Candidate.lean`；
- 执行 shell 命令和文件修改；
- 限制编译次数；
- 记录完整事件流；
- 收集最终候选证明。

因此，如果日志中出现 `command_execution`、`file_change` 和 `check_candidate.sh`，说明模型确实在走 Codex harness。

---

## 3. 密钥和 URL

### 3.0 统一模型 profile(MODEL_PROFILE)

所有入口脚本(run-codex / run-sglang / run-direct / run-remote / run-gpt-smoke)通过
`MODEL_PROFILE` 选择「模型 × 端点 × 接入方式」组合,profile 文件在 `configs/profiles/`,
由 `scripts/model-env.sh` 统一加载:

| profile | 接入方式 | 模型 | 凭据来源 |
|---|---|---|---|
| `sglang-ds4pro` | sglang 直连(无鉴权) | deepseek-v4-pro-0813 | 占位 EMPTY |
| `relay-glm53` | API 中转(token.pjlab.org.cn) | glm-5.3 | secret.txt「内部中转」段 |
| `relay-gpt6astra` | API 中转(外部) | gpt-6-astra | secret.txt「外部中转」段 |

sglang 直连与 API 中转的差异不在脚本里分支,全部由 profile 字段承载:
`SECRET_SECTION`(凭据从 secret.txt 哪个段解析)、`NO_PROXY_DOMAIN`、
`NO_OUTPUT_SCHEMA`(sglang 默认 1,见 5.1)、`STREAM`、`REASONING_EFFORT`。

优先级:命令行环境变量 > profile 文件 > 脚本兜底默认,因此临时覆盖仍然简单:

```bash
# 切到内部中转的 glm-5.3
MODEL_PROFILE=relay-glm53 RUN_ID=xxx bash scripts/run-codex-experiment.sh
# 沿用 sglang 端点但换模型名
MODEL_PROFILE=sglang-ds4pro MODEL=其他模型名 RUN_ID=xxx bash scripts/run-sglang-experiment.sh
```

新增模型/端点:复制一份 `configs/profiles/*.env` 改字段即可,不用动脚本。

### 3.1 推荐配置

在根目录创建本地文件 `secret.txt`：

```bash
export OPENAI_API_KEY='你的私有 Key'
export OPENAI_BASE_URL='http://或https://你的地址/v1'
```

然后设置权限：

```bash
chmod 600 secret.txt
```

`secret.txt` 已加入 `.gitignore`，不要将私钥复制到 Markdown、日志或 Git commit 中。

### 3.2 Base URL 规则

`run-logs/codex-gpt-custom` 使用 Responses API：

```text
OPENAI_BASE_URL + /responses
```

例如配置：

```text
OPENAI_BASE_URL=http://example:3888/v1
```

实际请求会发送到：

```text
http://example:3888/v1/responses
```

不要把 `/responses` 重复写进 `OPENAI_BASE_URL`。

### 3.3 查询端点实际开放的模型

模型显示名和 API 模型 ID 可能不同。开始大实验前应查询 `/models`：

```bash
source secret.txt

/root/miniconda3/envs/rlmeval/bin/python - <<'PY'
import json
import os
import urllib.request

base_url = os.environ["OPENAI_BASE_URL"].rstrip("/")
request = urllib.request.Request(
    base_url + "/models",
    headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]},
)
with urllib.request.urlopen(request, timeout=30) as response:
    model_ids = sorted(item["id"] for item in json.load(response)["data"])
for model_id in model_ids:
    print(model_id)
PY
```

当前曾验证过的精确模型 ID 包括：

```text
glm-5.3
gpt-6-astra
```
错误ID返回：```text503 No available channel for model ...```

---

## 4. 模型 wrapper 的选择

### 4.1 推荐：通用自定义 Responses wrapper

```text
run-logs/codex-gpt-custom
```

尽管文件名包含 `gpt`，它实际是通用 Responses API wrapper，可以用于：

- `glm-5.3`；
- `gpt-6-astra`；
- 端点 `/models` 中其他支持 Codex 工具调用的模型。

使用它时设置：

```bash
CODEX_WRAPPER=run-logs/codex-gpt-custom
SECRET_FILE=secret.txt
SOURCE_SECRET=1
```

### 4.2 旧 GLM lhcodex wrapper

```text
run-logs/codex-glm-lhcodex
```

该 wrapper 是早期实验兼容文件，包含固定的 provider 和 URL。除非需要复现实验，不建议继续在文件中内嵌 Key。新实验优先使用 `codex-gpt-custom + secret.txt`。

### 4.3 DS 内网 wrapper

```text
run-logs/codex-ds-internal
```

DS 需要本地清洗代理：

```bash
setsid nohup /root/miniconda3/envs/rlmeval/bin/python \
  run-logs/ds-responses-fix-proxy.py \
  > /data/projects/math-harness-eval/rlm-env/ds-proxy.log 2>&1 < /dev/null &

ss -tln | grep 4102
```

DS 运行时通常设置：

```bash
MODEL=deepseek-v4-pro-0813
CODEX_WRAPPER=run-logs/codex-ds-internal
SOURCE_SECRET=0
```

### 4.4 模型与 wrapper 示例

| 模型 | `MODEL` | `CODEX_WRAPPER` | 推理档建议 |
|---|---|---|---|
| GLM 5.3，自定义端点 | `glm-5.3` | `run-logs/codex-gpt-custom` | `high` |
| GPT Astra | `gpt-6-astra` | `run-logs/codex-gpt-custom` | `high` |
| GLM lhcodex 兼容配置 | `glm-5.3` | `run-logs/codex-glm-lhcodex` | 以端点支持为准 |
| DS 内网 | `deepseek-v4-pro-0813` | `run-logs/codex-ds-internal` | 以端点支持为准 |

当前自定义端点中的 `glm-5.3` 不接受 `xhigh`，会提示只支持 `low/high/max`。因此本文所有 GLM 示例默认使用：

```bash
REASONING_EFFORT=high
```

---

## 5. Harness 和任务类型

### 5.1 Codex harness

本手册使用：

```bash
./rlmv-eval run-codex
```

它使用 ProofNet-Verified 风格协议，让模型在 workspace 中读题、写 `Candidate.lean`、调用 `check_candidate.sh`，最后由 RLMEval 独立评分。

### 5.2 `TASK` 的选择

| `TASK` | 用途 | 主要评分字段 |
|---|---|---|
| `proof` | Easy proof track，补全证明 | `proof_ok` |
| `proof-normal` | Normal proof track | `proof_ok` |
| `statement` | statement autoformalization | `beq_plus_ok` |


### 5.3 旧的直接模型脚本

仓库原始 README 中的：

```text
scripts/eval_statement_autoformalization.py
scripts/eval_proof_autoformalization.py
```

属于另一条直接模型评测链路，不等同于 Codex harness。两类实验的工具权限、prompt、输出格式和评分过程不同，结果不应直接混在同一张表中。

---

## 6. 通用实验 runner

推荐统一使用：

```text
scripts/run-codex-experiment.sh
```

它会依次执行：

1. 加载 `secret.txt`；
2. 设置 HOME、缓存、Elan 和 PATH；
3. 运行 Codex harness 生成；
4. 对生成结果正式评分；
5. 调用统计脚本生成 `summary.md` 和 `summary.json`。

### 6.1 参数表

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `RUN_ID` | 无，必填 | 唯一实验 ID |
| `MODEL` | `glm-5.3` | API 模型 ID |
| `TASK` | `proof` | `proof` / `proof-normal` / `statement` |
| `INDICES` | `168,41,38` | 题目索引，支持 `all` |
| `SAMPLES` | `1` | 每题生成次数，即实验中的 k |
| `CONCURRENCY` | `4` | 同时运行的 harness 数量 |
| `REASONING_EFFORT` | `high` | 推理档 |
| `TMO` | `2400` | 单个 harness 超时秒数 |
| `MAX_COMPILE_ATTEMPTS` | `3` | workspace 内最大 Lean 检查次数 |
| `DATASET` | `data/rlm25_pfr_tlb.jsonl` | 数据集 JSONL |
| `CODEX_WRAPPER` | `run-logs/codex-gpt-custom` | Codex provider wrapper |
| `SECRET_FILE` | `secret.txt` | Key/URL 文件 |
| `SOURCE_SECRET` | `1` | 是否加载密钥文件 |
| `SUMMARY_DIR` | `run-logs/$RUN_ID` | 日志与汇总目录 |

### 6.2 `RUN_ID` 必须唯一

runner 不会覆盖已有：

```text
artifacts/<RUN_ID>/generations.jsonl
```

如果需要重跑，使用新的 ID：

```text
experiment-name-retry1
experiment-name-retry2
```

---

## 7. Smoke test

### 7.1 GLM 三题 smoke，Pass@1

```bash
cd /data/projects/math-harness-eval/RLMEval

RUN_ID=smoke-glm53-p1-$(date +%Y%m%d-%H%M%S) \
MODEL=glm-5.3 \
TASK=proof \
INDICES=168,41,38 \
SAMPLES=1 \
CONCURRENCY=3 \
REASONING_EFFORT=high \
CODEX_WRAPPER=run-logs/codex-gpt-custom \
bash scripts/run-codex-experiment.sh
```

### 7.2 GPT 三题 smoke，Pass@1

```bash
RUN_ID=smoke-gpt6astra-p1-$(date +%Y%m%d-%H%M%S) \
MODEL=gpt-6-astra \
TASK=proof \
INDICES=168,41,38 \
SAMPLES=1 \
CONCURRENCY=3 \
REASONING_EFFORT=high \
CODEX_WRAPPER=run-logs/codex-gpt-custom \
bash scripts/run-codex-experiment.sh
```

### 7.3 GLM 三题 Pass@16

Pass@16 表示每道题生成 16 次。因此三题总 harness 数量是：

```text
3 × 16 = 48
```

命令：

```bash
RUN_ID=smoke-glm53-p16-$(date +%Y%m%d-%H%M%S) \
MODEL=glm-5.3 \
TASK=proof \
INDICES=168,41,38 \
SAMPLES=16 \
CONCURRENCY=4 \
REASONING_EFFORT=high \
CODEX_WRAPPER=run-logs/codex-gpt-custom \
bash scripts/run-codex-experiment.sh
```

并发数只控制同时运行几个 harness，不改变总样本数。

---

## 8. 固定随机子集实验

使用：

```text
scripts/select_experiment_items.py
```

该脚本会生成：

```text
selection.json
selection.tsv
indices.txt
```

### 8.1 从 TLB 固定随机选择 20 题

```bash
SELECTION_DIR=run-logs/selections/tlb20-seed20261017

/root/miniconda3/envs/rlmeval/bin/python scripts/select_experiment_items.py \
  --dataset data/rlm25_pfr_tlb.jsonl \
  --project TLB \
  --count 20 \
  --seed 20261017 \
  --output-dir "$SELECTION_DIR"
```

运行 Pass@4：

```bash
RUN_ID=glm53-tlb20-p4-$(date +%Y%m%d-%H%M%S) \
MODEL=glm-5.3 \
TASK=proof \
INDICES="$(cat "$SELECTION_DIR/indices.txt")" \
SAMPLES=4 \
CONCURRENCY=4 \
REASONING_EFFORT=high \
CODEX_WRAPPER=run-logs/codex-gpt-custom \
bash scripts/run-codex-experiment.sh
```

总 harness 数量：

```text
20 × 4 = 80
```

### 8.2 排除已用于 smoke 的题

```bash
/root/miniconda3/envs/rlmeval/bin/python scripts/select_experiment_items.py \
  --project TLB \
  --count 20 \
  --seed 20261017 \
  --exclude 168,41,38 \
  --output-dir run-logs/selections/tlb20-no-smoke
```

### 8.3 从 PFR 选题

```bash
/root/miniconda3/envs/rlmeval/bin/python scripts/select_experiment_items.py \
  --project PFR \
  --count 20 \
  --seed 20261017 \
  --output-dir run-logs/selections/pfr20-seed20261017
```

---

## 9. 全量实验

### 9.1 完整 269 题，Pass@1

```bash
RUN_ID=glm53-all269-p1-$(date +%Y%m%d-%H%M%S) \
MODEL=glm-5.3 \
TASK=proof \
INDICES=all \
SAMPLES=1 \
CONCURRENCY=4 \
REASONING_EFFORT=high \
CODEX_WRAPPER=run-logs/codex-gpt-custom \
bash scripts/run-codex-experiment.sh
```

### 9.2 完整 269 题，Pass@4

```bash
RUN_ID=glm53-all269-p4-$(date +%Y%m%d-%H%M%S) \
MODEL=glm-5.3 \
TASK=proof \
INDICES=all \
SAMPLES=4 \
CONCURRENCY=4 \
REASONING_EFFORT=high \
CODEX_WRAPPER=run-logs/codex-gpt-custom \
bash scripts/run-codex-experiment.sh
```

这会创建：

```text
269 × 4 = 1076
```

个 harness 任务。运行前必须确认 API 额度、磁盘、机器负载和允许的并发。

### 9.3 只跑完整 TLB

先生成全部 TLB 索引。`--count 0` 表示选择所有匹配题：

```bash
SELECTION_DIR=run-logs/selections/tlb-all

/root/miniconda3/envs/rlmeval/bin/python scripts/select_experiment_items.py \
  --project TLB \
  --count 0 \
  --output-dir "$SELECTION_DIR"
```

然后运行：

```bash
RUN_ID=glm53-tlb124-p1-$(date +%Y%m%d-%H%M%S) \
MODEL=glm-5.3 \
TASK=proof \
INDICES="$(cat "$SELECTION_DIR/indices.txt")" \
SAMPLES=1 \
CONCURRENCY=4 \
REASONING_EFFORT=high \
bash scripts/run-codex-experiment.sh
```

### 9.4 只跑完整 PFR

```bash
SELECTION_DIR=run-logs/selections/pfr-all

/root/miniconda3/envs/rlmeval/bin/python scripts/select_experiment_items.py \
  --project PFR \
  --count 0 \
  --output-dir "$SELECTION_DIR"

RUN_ID=glm53-pfr145-p1-$(date +%Y%m%d-%H%M%S) \
MODEL=glm-5.3 \
TASK=proof \
INDICES="$(cat "$SELECTION_DIR/indices.txt")" \
SAMPLES=1 \
CONCURRENCY=4 \
REASONING_EFFORT=high \
bash scripts/run-codex-experiment.sh
```

### 9.5 关于旧 `run-glm-proof-full.sh`

`scripts/legacy/run-glm-proof-full.sh` 是早期兼容脚本（已移至 `scripts/legacy/`）：

- 使用硬编码索引列表；
- 使用旧 GLM wrapper；
- 推理档硬编码为 `xhigh`；
- 不自动生成通用统计报告。

新实验建议使用 `run-codex-experiment.sh`，并通过 `INDICES=all` 或选题脚本明确控制范围。

---

## 10. 后台启动

使用：

```text
scripts/start-codex-experiment-background.sh
```

后台启动器会：

- 使用 `setsid + nohup` 脱离当前终端；
- 写入 PID；
- 保存不包含密钥的启动配置；
- 将 stdout/stderr 写入 `background.log`；
- 实验结束后由通用 runner 自动生成统计报告。

### 10.1 后台启动一个 20 题 Pass@4 实验

```bash
SELECTION_DIR=run-logs/selections/tlb20-seed20261017

RUN_ID=glm53-tlb20-p4-background \
MODEL=glm-5.3 \
TASK=proof \
INDICES="$(cat "$SELECTION_DIR/indices.txt")" \
SAMPLES=4 \
CONCURRENCY=4 \
REASONING_EFFORT=high \
CODEX_WRAPPER=run-logs/codex-gpt-custom \
SECRET_FILE=secret.txt \
bash scripts/start-codex-experiment-background.sh
```

输出示例：

```text
background_pid=123456
log=run-logs/glm53-tlb20-p4-background/background.log
summary=run-logs/glm53-tlb20-p4-background/summary.md
```

### 10.2 监控后台任务

查看进程：

```bash
RUN_ID=glm53-tlb20-p4-background
PID=$(cat "run-logs/$RUN_ID/background.pid")
ps -p "$PID" -o pid,ppid,stat,etime,cmd
```

实时查看日志：

```bash
tail -f "run-logs/$RUN_ID/background.log"
```

查看已完成生成数：

```bash
wc -l "artifacts/$RUN_ID/generations.jsonl"
```

查看已完成评分数：

```bash
wc -l "artifacts/$RUN_ID/scores.jsonl"
```

查看有多少代理实际调用过工具：

```bash
rg -l '"type":"command_execution"|"type":"file_change"' \
  "artifacts/$RUN_ID/logs/"*.events.jsonl | wc -l
```

### 10.3 停止后台任务

确认确实需要停止后：

```bash
RUN_ID=glm53-tlb20-p4-background
PID=$(cat "run-logs/$RUN_ID/background.pid")
kill "$PID"
```

停止后不要使用相同 `RUN_ID` 直接重跑，因为可能已经存在部分 `generations.jsonl`。使用新的 `RUN_ID`。

---

## 11. 输出目录

每个 run 的主要输出：

```text
artifacts/<RUN_ID>/generations.jsonl
artifacts/<RUN_ID>/scores.jsonl
artifacts/<RUN_ID>/logs/*.events.jsonl
artifacts/<RUN_ID>/logs/*.stderr.log
agent_workspaces/<RUN_ID>/task-*/
run-logs/<RUN_ID>/config.txt
run-logs/<RUN_ID>/background.log
run-logs/<RUN_ID>/summary.md
run-logs/<RUN_ID>/summary.json
```

### 11.1 `generations.jsonl`

每行对应一个题目的一个样本，常用字段：

```text
item_index
item_name
item_repo
sample_id
model
status
wall_ms
compile_attempts
raw_text
agent_final_message
events_path
```

### 11.2 `scores.jsonl`

每行对应一个正式评分结果，proof track 常用字段：

```text
item_index
sample_id
generation_status
parse_ok
proof_ok
typecheck_ok
score_status
```

常见 `score_status`：

| 状态 | 含义 |
|---|---|
| `passed` | 证明通过正式 Lean 检查 |
| `placeholder_in_proof` | 候选仍包含 `sorry` / `admit` / `apply?` |
| `failed` | 候选未通过正式检查 |
| `proof_lean_error` | Lean 返回明确证明错误 |
| `statement_modified` | 模型修改了原定理声明 |
| `generation_error` | 模型/API/Codex 生成阶段失败 |
| `checker_error` | 评分器或 Lean 服务异常，不一定是模型证明错误 |

### 11.3 `events.jsonl`

事件日志用于判断模型是否真实使用 harness：

```bash
cat artifacts/<RUN_ID>/logs/<HASH>.events.jsonl
```

典型事件：

```text
thread.started
turn.started
reasoning
command_execution
file_change
agent_message
turn.completed
turn.failed
```

---

## 12. 统计脚本

通用统计脚本：

```text
scripts/summarize_codex_run.py
```

它直接读取：

```text
artifacts/<RUN_ID>/generations.jsonl
artifacts/<RUN_ID>/scores.jsonl
```

并输出：

```text
run-logs/<RUN_ID>/summary.md
run-logs/<RUN_ID>/summary.json
```

### 12.1 重新统计一个已完成实验

```bash
/root/miniconda3/envs/rlmeval/bin/python scripts/summarize_codex_run.py \
  --run-id glm-tlb20-pass4-20261017 \
  --dataset data/rlm25_pfr_tlb.jsonl \
  --expected-samples 4
```

### 12.2 指定输出目录

```bash
/root/miniconda3/envs/rlmeval/bin/python scripts/summarize_codex_run.py \
  --run-id glm-tlb20-pass4-20261017 \
  --expected-samples 4 \
  --output-dir run-logs/reports/glm-tlb20-pass4
```

### 12.3 当前 20 题实验的统计来源

`glm-tlb20-pass4-20261017` 的原始结果：

```text
80 个生成样本
80 个评分样本
13 个单次样本通过
7 道题至少一次通过
```

因此：

```text
单样本通过率 = 13 / 80 = 16.25%
Observed Pass@4 = 7 / 20 = 35%
```

这些值由统计脚本从 JSONL 逐行读取并计算，不是手工填写。

---

## 13. Pass@k 的解释

在当前实验报告中，一道题的 observed Pass@k 定义为：

```text
k 个样本中至少有 1 个 proof_ok=true
```

例如某题四次结果为：

```text
failed, passed, placeholder_in_proof, failed
```

则：

```text
passed_samples = 1
Pass@4 = yes
```

需要区分：

1. **单样本通过率**：所有成功样本数 / 所有评分样本数；
2. **题目 observed Pass@k**：至少成功一次的题目数 / 总题目数。

本手册中的 `summary.md` 使用第二种方式报告题目级 Pass@k。它是本次实际 k 次采样的 observed Pass@k，不是从其他采样数量估计出的无偏 pass@k estimator。

---

## 14. 只重新评分，不重新调用模型

如果模型生成已经完成，但评分阶段因 `lake`、磁盘 I/O 或 Lean 服务异常中断，不要重复消耗 API。直接重评分：

```bash
export HOME=/data/projects/math-harness-eval/rlm-env/home
export XDG_CACHE_HOME=$HOME/.cache
export ELAN_HOME=/data/projects/math-harness-eval/elan
export PATH="$ELAN_HOME/bin:$PATH"

RUN_ID=你的运行ID

./rlmv-eval score \
  --dataset data/rlm25_pfr_tlb.jsonl \
  --input "artifacts/$RUN_ID/generations.jsonl" \
  --output "artifacts/$RUN_ID/scores.jsonl" \
  --task proof

/root/miniconda3/envs/rlmeval/bin/python scripts/summarize_codex_run.py \
  --run-id "$RUN_ID"
```

评分器当前是顺序评分。某些 Lean 检查可能等待数分钟，日志短时间不更新不一定表示死锁。

---

## 15. 常见问题

### 15.1 `404 ... /responses`

原因：Base URL 不支持 Responses API，或 URL 层级错误。

检查：

```text
OPENAI_BASE_URL 应是基础 /v1 地址
wrapper 会自动追加 /responses
```

### 15.2 `503 No available channel for model ...`

可能原因：

- 模型 ID 拼错；
- 当前 Key 所属分组没有该模型；
- 上游通道暂时不可用。

先查询 `/models`，使用端点返回的精确 ID。

### 15.3 `该模型始终思考...请使用 low、high 或 max`

原因：端点不接受 `xhigh`。

解决：

```bash
REASONING_EFFORT=high
```

### 15.4 模型直接返回 completed，但没有调用工具

表现：

- `compile_attempts=0`；
- `Candidate.lean` 仍有 `sorry`；
- `events.jsonl` 没有 `command_execution` 或 `file_change`；
- 评分为 `placeholder_in_proof`。

这通常是模型没有遵循 Codex harness 协议，不是评分器错误。

### 15.5 `lake is not installed`

评分前确保：

```bash
export ELAN_HOME=/data/projects/math-harness-eval/elan
export PATH="$ELAN_HOME/bin:$PATH"
```

通用 runner 已自动设置。

### 15.6 `checker_error`

`checker_error` 可能来自：

- Lean REPL 超时；
- 磁盘 I/O 卡顿；
- 评分服务进程异常；
- 上下文初始化失败。

如果候选在任务内 `check_candidate.sh` 已成功，但正式评分为 `checker_error`，可以在机器负载较低时重新执行 score，而不用重新生成。

### 15.7 并发应该设多少

建议：

| 场景 | 建议并发 |
|---|---:|
| 三题 smoke | 3 |
| 20 题 Pass@4 | 3–4 |
| 长时间后台实验 | 4 |
| 已确认服务稳定且额度足够 | 可逐步提高，但先观察报警和限流 |

并发 8 曾可运行，但为了避免 API 报警、上游限流和本地 I/O 峰值，默认文档使用并发 4。

### 15.8 总任务数怎么算

```text
总 harness 数 = 题目数 × SAMPLES
```

示例：

```text
3 题 Pass@16  = 3 × 16  = 48
20 题 Pass@4  = 20 × 4  = 80
269 题 Pass@4 = 269 × 4 = 1076
```

`CONCURRENCY` 只控制同时运行数。

---

## 16. 推荐实验流程

每次更换模型、Key、URL 或推理档时，建议严格按以下顺序：

1. 查询 `/models`，确认精确模型 ID；
2. 单题、单并发 smoke；
3. 三题 Pass@1 smoke；
4. 三题小 Pass@k；
5. 固定随机 20 题 Pass@1；
6. 20 题 Pass@4；
7. 确认 API、工具调用、Lean 评分和成本后再跑全量。

推荐单题命令：

```bash
RUN_ID=glm53-single-168-$(date +%Y%m%d-%H%M%S) \
MODEL=glm-5.3 \
TASK=proof \
INDICES=168 \
SAMPLES=1 \
CONCURRENCY=1 \
REASONING_EFFORT=high \
bash scripts/run-codex-experiment.sh
```

---

## 17. 实验完成检查清单

生成阶段：

```bash
test -f "artifacts/$RUN_ID/generations.jsonl"
wc -l "artifacts/$RUN_ID/generations.jsonl"
```

评分阶段：

```bash
test -f "artifacts/$RUN_ID/scores.jsonl"
wc -l "artifacts/$RUN_ID/scores.jsonl"
```

统计报告：

```bash
test -f "run-logs/$RUN_ID/summary.md"
cat "run-logs/$RUN_ID/summary.md"
```

后台实验：

```bash
cat "run-logs/$RUN_ID/background.pid"
cat "run-logs/$RUN_ID/background.log"
cat "run-logs/$RUN_ID/launch.txt"
```

最终应保留：

- 实验的唯一 `RUN_ID`；
- 模型、wrapper、推理档、并发和样本数；
- 明确的选题清单或 `INDICES=all`；
- `generations.jsonl`；
- `scores.jsonl`；
- `summary.md`；
- `summary.json`；
- 必要时保留 API/Lean 错误日志。

这样后续可以在不重新调用模型的情况下复核统计、重新评分或比较不同模型。
