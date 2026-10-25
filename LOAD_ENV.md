# RLMEval (RLM25) PFR+TLB bench 从零搭建指南

> 在一台全新机器上、不依赖任何现成产物，从上游 GitHub 开始搭出与
> ProofNet-Verified / FormalTCS 并列的第三个 bench：RLMEval 的 **PFR + TLB** 两个子集，
> 套在 codex agent harness 里。自研适配器源码全部内嵌在附录 C/D/E，按顺序粘贴即可。
> 全程约 1.5–2 小时（大头是 mathlib 缓存下载和基准抽取）。

## 0. 产物清单（搭完应得到）

| 产物 | 路径 | 规模 |
|---|---|---|
| 评测仓库（上游 + 自研适配器） | `math-harness-nvme-test/RLMEval` | ~23G（含 venv/traced_repos） |
| 题库 | `RLMEval/data/rlm25_pfr_tlb.jsonl` | 269 题（PFR 145 / TLB 124；proof 可做 220） |
| Lean 环境 | `rlm-env/pfr`、`rlm-env/tlb` | 各 ~5G |
| 缓存/中间物 | `rlm-env/home` | ~14G |

**路径约定**：全文以 `/data/projects/math-harness-eval` 为家。用户名/盘符不同请全文替换；
该盘需 ≥120G 空闲、不是 tmpfs；Home目录若小，一切缓存都要指到数据盘。

## 1. 前置条件——安装lean

```bash
# 1.1 基础工具
git --version && /root/miniconda3/bin/conda --version
# 1.2 网络：外网走代理（按机房实际填）；内网 *.pj-service.org.cn 与 127.0.0.1 不走
export https_proxy=http://<proxy>:3128 http_proxy=$https_proxy
# 1.3 创建这个项目专用的 elan 并装在数据盘
export ELAN_HOME=/data/projects/math-harness-eval/elan
curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh -s -- -y --no-modify-path
export PATH="$ELAN_HOME/bin:$PATH"
elan toolchain install leanprover/lean4:v4.14.0-rc3
elan toolchain install leanprover/lean4:v4.13.0-rc3
# 1.4 codex CLI（内部构建，>=0.158；有 ProofNet-Verified .toolchains 可直接复用其路径）
export CODEX_BIN=<codex 可执行文件绝对路径>
"$CODEX_BIN" --version
```

| 组件 | 版本/commit |
|---|---|
| PFR | `f6bdcac2365623d3667d3ff8fd8ddb7f95ce2313`（lean v4.14.0-rc3） |
| TLB | `0f09ff100a06a5e4542181514bfff74213ae126b`（lean v4.13.0-rc3） |
| lean-dojo | **必须 ==2.2.0**（uv 默认解出 4.20，与旧工具链不兼容） |
| codex | ≥0.158（0.162.1 亦可；wire_api 只支持 responses） |

## 2. 拉取仓库源码，并增加适配代码

```bash
mkdir -p /data/projects/math-harness-eval && cd /data/projects/math-harness-eval
git clone https://github.com/augustepoiroux/RLMEval
cd RLMEval
mkdir -p src/rlm_agent patches run-logs/bin
```

把 **附录 C**（venv 补丁）、**附录 D**（适配器源码）、**附录 E**（端点/沙箱组件）
的每个代码块按其文件名落盘（`cat > <文件名> <<'EOF' ... EOF` 或编辑器粘贴），然后：

```bash
chmod +x rlmv-eval run-logs/codex-gpt-custom run-logs/bin/apply_patch scripts/*.sh
```

## 3. 基于Python 3.11 配置项目依赖环境，并修改lean dojo==2.2.0的源码

```bash
# 本机已使用 conda 环境 rlmeval；如需重建，请用 conda 创建 Python 3.11 环境。
/root/miniconda3/bin/conda run -n rlmeval python -m pip install -e .
/root/miniconda3/bin/conda run -n rlmeval python -m pip install --no-deps "lean-dojo==2.2.0"
/root/miniconda3/envs/rlmeval/bin/python patches/apply_all.py   # 幂等，可重复运行
```

补丁解决：Lean Dojo的几个缺点，包括GitHub 匿名 REST 限流绕行、`.git` 后缀 raw 404、lean4 tag 解析、
plasTeX kpsewhich 绝对路径 bug（对应坑表 3/4/5）。

## 4. 准备PFR+TLB的评测环境（复制两份+编译一份）

- `rlm-env/pfr`、`rlm-env/tlb`：**可编译环境**（agent 编译反馈 + 评分）
- `rlm-env/pfr-src`、`rlm-env/tlb-src`：**抽取输入**，必须无 `.lake` 的纯净克隆——
  带 `.lake` 的克隆会让 dojo 的 lake build 变 no-op、跳过插桩，抽出 0 条声明（坑 6）

```bash
git clone https://github.com/teorth/pfr /data/projects/math-harness-eval/rlm-env/pfr
cd /data/projects/math-harness-eval/rlm-env/pfr && git checkout f6bdcac2365623d3667d3ff8fd8ddb7f95ce2313
git clone https://github.com/RemyDegenne/testing-lower-bounds /data/projects/math-harness-eval/rlm-env/tlb
cd /data/projects/math-harness-eval/rlm-env/tlb && git checkout 0f09ff100a06a5e4542181514bfff74213ae126b
git clone /data/projects/math-harness-eval/rlm-env/pfr /data/projects/math-harness-eval/rlm-env/pfr-src
cd /data/projects/math-harness-eval/rlm-env/pfr-src && git checkout f6bdcac2365623d3667d3ff8fd8ddb7f95ce2313
git clone /data/projects/math-harness-eval/rlm-env/tlb /data/projects/math-harness-eval/rlm-env/tlb-src
cd /data/projects/math-harness-eval/rlm-env/tlb-src && git checkout 0f09ff100a06a5e4542181514bfff74213ae126b
```

构建给编译反馈用的环境（约 20 分钟）：

```bash
mkdir -p /data/projects/math-harness-eval/rlm-env/home/.cache
ln -sfn $ELAN_HOME /data/projects/math-harness-eval/rlm-env/home/.elan
cat > /data/projects/math-harness-eval/rlm-env/build-lean.sh <<'BUILDEOF'
#!/usr/bin/env bash
set -euo pipefail
export ELAN_HOME=/data/projects/math-harness-eval/elan
export HOME=/data/projects/math-harness-eval/rlm-env/home
export XDG_CACHE_HOME=$HOME/.cache
export GIT_CONFIG_GLOBAL=/dev/null
export PATH="$ELAN_HOME/bin:$PATH"
for repo in pfr tlb; do
  cd /data/projects/math-harness-eval/rlm-env/$repo
  echo "[$(date -Is)] $repo: $(cat lean-toolchain)"
  lake exe cache get 2>&1 | tail -2
  lake build 2>&1 | tail -3
  echo "[$(date -Is)] $repo: BUILD DONE"
done
BUILDEOF
bash /data/projects/math-harness-eval/rlm-env/build-lean.sh
```

验收：两行 `BUILD DONE`；`rlm-env/pfr/.lake/build/lib/PFR.olean`、
`rlm-env/tlb/.lake/build/lib/TestingLowerBounds.olean` 存在。

## 5. 抽取基准lean代码并转为json（~40 分钟/仓库）

```bash
cat > /data/projects/math-harness-eval/rlm-env/run-extract.sh <<'EXTRACTEOF'
#!/usr/bin/env bash
set -euo pipefail
export HOME=/data/projects/math-harness-eval/rlm-env/home
export XDG_CACHE_HOME=$HOME/.cache
export ELAN_HOME=$HOME/.elan
export GIT_CONFIG_GLOBAL=/dev/null
export LEAN_DOJO_NO_GITHUB_API=1
export TMPDIR=/data/projects/math-harness-eval/rlm-env/tmp
export TMP=$TMPDIR
mkdir -p "$TMPDIR"
cd /data/projects/math-harness-eval/RLMEval
/root/miniconda3/envs/rlmeval/bin/python scripts/extract_benchmark.py --config configs/benchmark/pfr_tlb.yaml
EXTRACTEOF
chmod +x /data/projects/math-harness-eval/rlm-env/run-extract.sh
bash /data/projects/math-harness-eval/rlm-env/run-extract.sh
```

关键点：`LEAN_DOJO_NO_GITHUB_API=1` 绕 REST 限流；`TMPDIR` 指数据盘（/tmp 若是
tmpfs 会被 dojo 的拷贝撑爆，坑 2）。

**TLB 大概率在 blueprint 步骤报 `chapter` ENOENT**（上游 extractor 的 chdir 副作用，
坑 7；PFR 不受影响）。PFR 成功后，在 RLMEval 目录下手工补齐 TLB：

```bash
/root/miniconda3/envs/rlmeval/bin/python - <<'TLBEOF'
import os, json
os.environ["HOME"] = "/data/projects/math-harness-eval/rlm-env/home"
os.environ["TMPDIR"] = "/data/projects/math-harness-eval/rlm-env/tmp"
import jsonlines
from rlm_eval.data_processing.blueprint_extractor import extract_blueprint_info
from rlm_eval.data_processing.blueprint_lean_linking import merge_blueprint_lean_dep_graphs
out = os.path.abspath("traced_repos/tlb-src_0f09ff100a06a5e4542181514bfff74213ae126b")
bp = extract_blueprint_info(f"{out}/tlb-src/blueprint")
with jsonlines.open(f"{out}/blueprint.jsonl", "w") as w:
    w.write_all(bp)
os.chdir("/data/projects/math-harness-eval/RLMEval")
merged = merge_blueprint_lean_dep_graphs(bp, list(jsonlines.open(f"{out}/lean_declarations.jsonl")))
with jsonlines.open(f"{out}/blueprint_to_lean.jsonl", "w") as w:
    w.write_all(merged)
json.dump([["PFR", "Success"], ["TLB", "Success"]], open("traced_repos/success.json", "w"))
print("TLB nodes:", len(bp), "theorem-linked:", len(merged))
TLBEOF
```

验收：PFR `blueprint_to_lean.jsonl` 216 节点/172 theorem-linked、
`lean_declarations.jsonl` 1064 条；TLB 345/132；两边 `lean_files.jsonl` 非空。

## 6. 使用json文件 构建题库jsonl，形成标准评测条目

```bash
./rlmv-eval items --config configs/benchmark/pfr_tlb.yaml \
  --out data/rlm25_pfr_tlb.jsonl \
  --project-map "PFR=/data/projects/math-harness-eval/rlm-env/pfr,TLB=/data/projects/math-harness-eval/rlm-env/tlb"
# 期望: wrote 269 items ... {'PFR': 145, 'TLB': 124}
```

## 7. 模型与harness接入

### 7.1 统一接入：MODEL_PROFILE（2026-10-25 起）

所有入口脚本（run-codex / run-sglang / run-direct / run-remote / run-gpt-smoke）通过
`MODEL_PROFILE` 选择「模型 × 端点 × 接入方式」，配置统一收敛在两处：

- `scripts/model-env.sh`：加载器（供入口脚本 source，勿直接执行）
- `configs/profiles/<name>.env`：一个文件 = 一个组合，新增模型/端点只需复制改字段

| profile | 接入方式 | 模型 | 凭据 |
|---|---|---|---|
| `sglang-ds4pro` | sglang 直连（无鉴权） | deepseek-v4-pro-0813 | 占位 EMPTY |
| `relay-glm53` | API 中转 token.pjlab.org.cn | glm-5.3 | secret.txt「内部中转」段 |
| `relay-gpt6astra` | API 中转（外部） | gpt-6-astra | secret.txt「外部中转」段 |

profile 示例（`configs/profiles/sglang-ds4pro.env`）：

```bash
FLAVOR=sglang                                   # sglang 直连 | relay API 中转（元数据）
MODEL=${MODEL:-deepseek-v4-pro-0813}
BASE_URL=${BASE_URL:-http://s-20261019104211-rcw2d.ailab-ma4agismall.pjh-service.org.cn/v1}
API_KEY=${API_KEY:-EMPTY}                       # relay 不写此项，改配 SECRET_SECTION
NO_PROXY_DOMAIN=${NO_PROXY_DOMAIN:-.pjh-service.org.cn}
NO_OUTPUT_SCHEMA=${NO_OUTPUT_SCHEMA-1}          # sglang 的 text.format 会杀死工具调用
STREAM=${STREAM-1}                              # direct 轨道默认流式
REASONING_EFFORT=${REASONING_EFFORT-high}
```

加载器行为：source profile（`${VAR-default}` 写法，优先级 = 命令行环境变量 > profile >
脚本兜底）→ 按 `SECRET_SECTION` 从 `secret.txt` 解析凭据 → export
`OPENAI_API_KEY/OPENAI_BASE_URL` 给 codex wrapper → 按 `NO_PROXY_DOMAIN` 并入 NO_PROXY。
relay 型 profile 的凭据放在 `secret.txt`（600 权限、勿入库，已加 .gitignore）：

```
## 外部中转
export OPENAI_API_KEY='...'
export OPENAI_BASE_URL='...'
## 内部中转
export OPENAI_API_KEY='...'
export OPENAI_BASE_URL='...'
```

### 7.2 历史接入方式（已废弃，源码快照见附录 E）

- GLM lhcodex wrapper（E.1）：外部域名不稳定，已删除；
- DS 内网清洗代理（E.3 / 坑 10）：新 sglang 端点 + codex >= 0.163 后不再需要；
- 旧一次性实验脚本（run-glm-proof-full.sh 等）已移至 `scripts/legacy/`。

### 7.3 apply_patch shim
codex 沙箱内没有 `apply_patch`，模型撞上会直接放弃（坑 9）。附录 E.4 落盘即可，
两个 wrapper 已注入 PATH。

## 8. 验证（对照基线）

```bash
export ELAN_HOME=/data/projects/math-harness-eval/elan CODEX_BIN=<codex 路径>
# DS（sglang 直连），期望 3/3
MODEL_PROFILE=sglang-ds4pro TASK=proof INDICES=168,41,38 TMO=2400 \
  RUN_ID=verify-ds bash scripts/run-codex-experiment.sh
# GLM（内部中转），期望 2/3（38,168 过）
MODEL_PROFILE=relay-glm53 TASK=proof INDICES=168,41,38 TMO=2400 \
  RUN_ID=verify-glm bash scripts/run-codex-experiment.sh
```

| 模型 | statement | proof(Easy) | proof(Normal) |
|---|---|---|---|
| glm-5.3 | 1/3 | 2/3 | 2/3 |
| deepseek-v4-pro-0813 | - | 3/3 | - |

## 9. 运行手册

```bash
# 三任务: statement | proof (Easy) | proof-normal (Normal)
# codex harness 轨道（换模型 = 换 MODEL_PROFILE）
MODEL_PROFILE=sglang-ds4pro TASK=proof INDICES=all TMO=2400 \
  RUN_ID=<id> bash scripts/run-codex-experiment.sh
# 裸模型单发轨道（track=direct_model：单次调用、无工具循环）
MODEL_PROFILE=relay-glm53 RUN_ID=<id> bash scripts/run-direct-experiment.sh
# 远程全量顺序批（PFR→TLB，单题失败不中断）
RUN_ID=<id> bash scripts/run-remote-full-sequential.sh
```

任务语义（对齐上游论文）：statement = BEq+ 判候选陈述与金陈述等价；proof = 金陈述 +
证明体编译 `allow_sorry=False`，pass@n；normal = 给模型的上下文剥掉非 blueprint 引理
（仅展示层，评分仍在完整上下文）。评分细则：`sorry/admit/apply?` 快筛；陈述须与金
declsig 一致（两侧剥文档注释；接受 `:= <term>` 项式证明）；PFR 重上下文 REPL
`timeout_context≥900s`（适配器默认已设）。

## 10. 坑全集（症状 / 根因 / 处置）

| # | 症状 | 根因 | 处置 |
|---|---|---|---|
| 1 | uv/pip ENOSPC | 缓存放满的家目录 | `UV_CACHE_DIR` 指数据盘 |
| 2 | 抽取时机器卡死 | `/tmp` 是 tmpfs，dojo 往里拷 5G+ | `TMPDIR` 指数据盘 |
| 3 | GitHub API 403 限流 | dojo 对依赖查 REST API | `LEAN_DOJO_NO_GITHUB_API=1` + 附录 C 补丁 |
| 4 | ExtractData 类型错/findLean panic | lean-dojo ≠ 2.2.0 | 钉 2.2.0 |
| 5 | `Could not find ... web.tex` | plasTeX kpsewhich 绝对路径 bug | 附录 C 补丁 |
| 6 | 抽取"成功"但 0 声明 | 输入克隆带 `.lake` 跳过插桩 | 纯净克隆 pfr-src/tlb-src |
| 7 | TLB `chapter` ENOENT | extractor chdir 副作用 | §5 手工补齐脚本 |
| 8 | agent 反馈全是 `no default toolchain` / `read-only .lake/config` | codex 沙箱内 elan/lake 不可用 | 适配器已内置直调 lean（prep 时沙箱外解析二进制 + LEAN_PATH） |
| 9 | `apply_patch: command not found`、模型躺平 | 沙箱 PATH 无此命令 | run-logs/bin shim + wrapper PATH 注入 |
| 10 | DS `error decoding response body` | sglang created_at 浮点 + 请求 reasoning 对象 + reasoning.* include | 清洗代理（附录 E.3） |
| 11 | DS 好证明被判 statement_modified | `:= <term>` 项式 vs 字面 `:= by` | 适配器按 declsig 比对 + 整体编译 |
| 12 | statement_modified 误判 | dojo declsig 自带文档注释 | 两侧剥注释（适配器已处理） |
| 13 | 评分 REPL 超时 | PFR 重上下文加载慢 | timeout_context=900（适配器默认） |
| 14 | 长任务被杀 | 会话级 2h 上限 | nohup/setsid 常驻 |

## 附录 C：venv 补丁（patches/apply_all.py）

```python
#!/usr/bin/env python3
"""RLMEval venv 补丁: lean-dojo==2.2.0 的 3 处 + plasTeX kpsewhich 的 1 处。
用法: /root/miniconda3/envs/rlmeval/bin/python patches/apply_all.py  (可重复运行, 已打则跳过)。
每个替换都断言锚点唯一, 打不上会报错退出而不是静默失败。"""
import re
import sys
import sysconfig
from pathlib import Path

VENV = Path(sys.prefix)
SITE = Path(sysconfig.get_paths()["purelib"])
LEAN_PY = SITE / "lean_dojo" / "data_extraction" / "lean.py"
TEX_PY = SITE / "plasTeX" / "TeX.py"


def patch(path: Path, replacements: list[tuple[str, str]], name: str) -> None:
    src = path.read_text()
    changed = False
    for old, new in replacements:
        sentinel = new[:40]
        if sentinel in src.replace(old, "", 1):
            continue  # already applied
        count = src.count(old)
        if count != 1:
            sys.exit(f"[{name}] anchor count={count} (expect 1), abort: {old[:60]!r}")
        src = src.replace(old, new)
        changed = True
    if changed:
        path.write_text(src)
    print(f"[{name}] {'patched' if changed else 'already ok'}")


# ---- lean-dojo 2.2.0: 1) normalize_url 剥 .git ----
patch(
    LEAN_PY,
    [(
        '''    # Remove trailing `/`.
    url = _URL_REGEX.fullmatch(url)["url"]  # type: ignore
    return ssh_to_https(url)''',
        '''    # Remove trailing `/`.
    url = _URL_REGEX.fullmatch(url)["url"]  # type: ignore
    url = ssh_to_https(url)
    if url.endswith(".git"):
        url = url[: -len(".git")]
    return url''',
    )],
    "lean_dojo normalize_url",
)

# ---- lean-dojo 2.2.0: 2) url_to_repo 限流 stub ----
STUB = '''

def _github_repo_name_stub(url: str):
    """Name-only stand-in for github.Repository; safe when commits are full hashes."""

    class _GithubRepoNameStub:
        def __init__(self, url: str) -> None:
            parts = url.rstrip("/").split("/")
            self.full_name = "/".join(parts[-2:])
            self.name = parts[-1]
            self.html_url = url
            self.clone_url = url + ".git"
            self.description = None
            self.default_branch = "master"

    return _GithubRepoNameStub(url)

'''
patch(
    LEAN_PY,
    [
        (
            "def url_to_repo(",
            STUB.lstrip("\n") + "def url_to_repo(",
        ),
        (
            '''            if repo_type == RepoType.GITHUB:
                return GITHUB.get_repo("/".join(url.split("/")[-2:]))''',
            '''            if repo_type == RepoType.GITHUB:
                if os.environ.get("LEAN_DOJO_NO_GITHUB_API"):
                    return _github_repo_name_stub(url)
                return GITHUB.get_repo("/".join(url.split("/")[-2:]))''',
        ),
    ],
    "lean_dojo url_to_repo",
)

# ---- lean-dojo 2.2.0: 3) lean4 tag -> git ls-remote ----
patch(
    LEAN_PY,
    [(
        '''    global LEAN4_REPO
    if LEAN4_REPO is None:
        LEAN4_REPO = GITHUB.get_repo("leanprover/lean4")
    assert "content" in config_dict, "config_dict must have a 'content' field"
    version = get_lean4_version_from_config(config_dict["content"].strip())''',
        '''    assert "content" in config_dict, "config_dict must have a 'content' field"
    version = get_lean4_version_from_config(config_dict["content"].strip())
    if os.environ.get("LEAN_DOJO_NO_GITHUB_API"):
        import subprocess

        tag = version if version.startswith("v") else "v" + version
        if tag.startswith("vnightly-"):
            repo_url = "https://github.com/leanprover/lean4-nightly"
            tag = "v" + version[len("vnightly-"):]
        else:
            repo_url = "https://github.com/leanprover/lean4"
        out = subprocess.run(
            ["git", "ls-remote", repo_url, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
            capture_output=True, text=True, timeout=120,
        ).stdout
        peeled = full = None
        for line in out.splitlines():
            sha, ref = line.split("\\t")
            if ref.endswith("^{}"):
                peeled = sha
            else:
                full = sha
        commit = peeled or full
        if commit and re.fullmatch(r"[0-9a-f]{40}", commit):
            return commit
        raise RuntimeError(
            f"LEAN_DOJO_NO_GITHUB_API=1: could not resolve {repo_url} tag {tag} via git ls-remote:\\n{out}"
        )
    global LEAN4_REPO
    if LEAN4_REPO is None:
        LEAN4_REPO = GITHUB.get_repo("leanprover/lean4")''',
    )],
    "lean_dojo lean4 tag",
)

# ---- plasTeX kpsewhich: 绝对路径直接返回 ----
patch(
    TEX_PY,
    [(
        """        restore_texinputs()
        raise FileNotFoundError('Could not find any file named: %s' % name)""",
        """        if os.path.isfile(name):
            return name
        restore_texinputs()
        raise FileNotFoundError('Could not find any file named: %s' % name)""",
    )],
    "plasTeX kpsewhich",
)
print("all patches ok")
```

## 附录 D：自研适配器源码

### D.1 src/rlm_agent/items.py

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import jsonlines
import yaml
from lean_interact.utils import clean_theorem_string

from rlm_eval.data_processing.lean_utils import LeanFilesProcessor, trim_comments_end
from rlm_eval.utils import ROOT_DIR


@dataclass(frozen=True)
class RlmItem:
    index: int
    repo: str
    project_name: str
    project_dir: str
    label: str
    name: str
    file: str
    informal_stmt: str
    informal_proof: str
    decl: str
    gt_proof_len: int
    formal_stmt: str
    context: str
    context_normal: str

    def to_row(self) -> dict:
        return {
            "index": self.index,
            "repo": self.repo,
            "project_name": self.project_name,
            "project_dir": self.project_dir,
            "label": self.label,
            "name": self.name,
            "file": self.file,
            "informal_stmt": self.informal_stmt,
            "informal_proof": self.informal_proof,
            "decl": self.decl,
            "gt_proof_len": self.gt_proof_len,
            "formal_stmt": self.formal_stmt,
            "context": self.context,
            "context_normal": self.context_normal,
        }


def _clean_text(text: str) -> str:
    return "\n".join(line.strip() for line in text.split(r"\\") if line.strip())


def _informal_text(node: dict) -> str:
    return "\n".join(line.strip() for line in node["processed_text"].split(r"\\") if line.strip())


def _is_theorem(node: dict) -> bool:
    if "lean_declarations" not in node or not node["lean_declarations"]:
        return False
    return "theorem_info" in node["lean_declarations"][0]


def _lean_context(file_content: str, start_idx: int) -> str:
    """Same context trimming as RLMEval _process_predictions."""
    original = file_content[:start_idx]
    trimmed = trim_comments_end(original).rstrip()
    if "\n" in trimmed:
        lean_context, last_line = trimmed.rsplit("\n", 1)
    else:
        lean_context, last_line = "", trimmed
    if last_line.endswith(" in"):
        lean_context += "\n" + last_line[:-3]
    else:
        lean_context = original
    if not lean_context.strip():
        lean_context = "-- context stub"
    return lean_context


def build_items(config_path: Path, *, project_override: dict[str, str] | None = None) -> list[RlmItem]:
    config = yaml.safe_load(config_path.read_text())
    traced_dir = Path(ROOT_DIR) / "traced_repos"
    items: list[RlmItem] = []
    index = 0
    for repo in config["repositories"]:
        repo_dir_name = repo["git_url"].split("/")[-1]
        project_dir = f"{repo_dir_name}_{repo['commit']}"
        root_dir = traced_dir / project_dir
        with jsonlines.open(root_dir / "blueprint_to_lean.jsonl") as reader:
            nodes = list(reader)
        with jsonlines.open(root_dir / "lean_files.jsonl") as reader:
            lean_files = {row["file"]: row["content"] for row in reader}
        with jsonlines.open(root_dir / "lean_declarations.jsonl") as reader:
            repo_lean_declarations = list(reader)
        blueprint_whitelist = {
            d["full_name"]
            for node in nodes
            for d in node.get("lean_declarations", [])
            if "full_name" in d
        }
        for node in nodes:
            if not node.get("label") or "lean_declarations" not in node or not _is_theorem(node):
                continue
            with_file = [d for d in node["lean_declarations"] if "file" in d]
            if len(with_file) != 1:
                continue
            decl = with_file[0]
            formal = clean_theorem_string(
                decl["theorem_info"]["declsig_no_comments"],
                new_theorem_name=decl["name"],
                add_sorry=True,
            )
            if formal is None:
                continue
            content = lean_files.get(decl["file"])
            if content is None:
                continue
            index += 1
            lean_root = str((root_dir / repo_dir_name).resolve())
            if project_override and repo["project_name"] in project_override:
                lean_root = project_override[repo["project_name"]]
            proof_text = (node.get("proof") or {}).get("text") or ""
            declsig = decl["theorem_info"].get("declsig") or ""
            gt_proof = decl["theorem_info"].get("proof") or ""
            items.append(
                RlmItem(
                    index=index,
                    repo=repo["project_name"],
                    project_name=repo["project_name"],
                    project_dir=lean_root,
                    label=node["label"],
                    name=decl["name"],
                    file=decl["file"],
                    informal_stmt=_informal_text(node),
                    informal_proof=_clean_text(proof_text),
                    decl=(declsig.strip() + " := by") if declsig.strip() else "",
                    gt_proof_len=len(gt_proof),
                    formal_stmt=formal,
                    context=_lean_context(content, decl["start_idx"]),
                    context_normal=LeanFilesProcessor(repo_lean_declarations).remove_theorems(
                        decl["file"],
                        _lean_context(content, decl["start_idx"]),
                        whitelist=blueprint_whitelist,
                    ),
                )
            )
    return items


def load_items(path: Path) -> dict[int, RlmItem]:
    items: dict[int, RlmItem] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        item = RlmItem(**row)
        items[item.index] = item
    if not items:
        raise ValueError(f"No items in {path}")
    return items


def parse_indices(spec: str, available: list[int]) -> list[int]:
    valid = set(available)
    if spec.strip().lower() in {"all", "*"}:
        return sorted(valid)
    chosen: set[int] = set()
    for part in spec.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            chosen.update(range(int(start_text), int(end_text) + 1))
        else:
            chosen.add(int(token))
    missing = sorted(chosen - valid)
    if missing:
        raise ValueError(f"Unknown item indices: {missing}")
    return sorted(chosen)
```

### D.2 src/rlm_agent/runner.py

```python
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shlex
import stat
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .items import RlmItem

DISABLED_CODEX_FEATURES = (
    "apps",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
)
MAX_CANDIDATE_BYTES = 256 * 1024
MAX_STDOUT_BYTES = 64 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunConfig:
    model: str
    codex_bin: str
    timeout_seconds: int
    max_compile_attempts: int
    reasoning_effort: str | None
    artifacts_dir: Path
    workspaces_dir: Path
    concurrency: int = 1
    samples: int = 1
    task: str = "statement"


_LEAN_ENV_CACHE: dict[str, tuple[str, str]] = {}


def _resolve_lean_env(project_dir: str, elan_home: Path) -> tuple[str, str]:
    """Resolve the pinned lean binary and LEAN_PATH for a repo (outside the sandbox).

    Bypasses elan/lake entirely inside the agent sandbox: the elan shim cannot resolve
    toolchains from the workspace cwd and lake tries to rewrite the read-only .lake/config.
    """
    key = str(project_dir)
    if key in _LEAN_ENV_CACHE:
        return _LEAN_ENV_CACHE[key]
    toolchain = (Path(project_dir) / "lean-toolchain").read_text().strip()
    toolchain_dir = toolchain.replace("/", "--").replace(":", "---")
    lean_bin = str(Path(elan_home) / "toolchains" / f"leanprover--lean4---{toolchain_dir}" / "bin" / "lean")
    lean_bin = lean_bin.replace("leanprover--lean4---leanprover--lean4---", "leanprover--lean4---")
    if not Path(lean_bin).is_file():
        raise FileNotFoundError(f"toolchain binary not found: {lean_bin}")
    entries = [str(Path(project_dir) / ".lake" / "build" / "lib")]
    packages = Path(project_dir) / ".lake" / "packages"
    if packages.is_dir():
        entries.extend(str(p / ".lake" / "build" / "lib") for p in sorted(packages.iterdir()) if (p / ".lake" / "build" / "lib").is_dir())
    lean_path = ":".join(entries)
    _LEAN_ENV_CACHE[key] = (lean_bin, lean_path)
    return lean_bin, lean_path

def _task_file_proof(item: RlmItem, max_compile_attempts: int) -> str:
    return f"""# RLM25 proof formalization task ({item.repo})

`Candidate.lean` already contains the target theorem statement followed by `:= by sorry`.
Write a complete Lean 4 tactic proof that replaces the `sorry`. The theorem statement itself
must remain byte-identical: do not rename it, do not add or change hypotheses, do not add
imports, `open`, namespaces, axioms, definitions, or a second declaration.
`Context.lean` contains the Lean context (imports, namespaces, and the theorems of the paper
blueprint) available to you. The hidden file `.context-full.lean` is part of the checking
infrastructure: do not read, copy, or otherwise access it; the compiler uses it internally.
Your proof may use any lemma available in `Context.lean` or in Mathlib.
The informal statement and informal proof from the paper blueprint are given below as a hint;
you do not need to follow them line by line if a cleaner Lean proof works.
Your proof must not contain `sorry`, `admit`, `axiom`, `native_decide`, or `apply?`.
Edit only `Candidate.lean`. You may run `./check_candidate.sh` at most {max_compile_attempts} times.
Use only `./check_candidate.sh` for compilation; never invoke `lean` or `lake` directly.
Do not read, write, remove, or otherwise access `.compile_count`; the wrapper enforces the budget.
Do not inspect files outside this task directory and do not use the network.
When finished successfully, respond with exactly this JSON object and no extra keys:
`{{"candidate_path":"Candidate.lean","status":"completed"}}`
Do NOT respond before you have read this file and `Context.lean`, written your best proof into
`Candidate.lean`, and run `./check_candidate.sh` at least once; an unattempted answer is a protocol
violation. Only after a real attempt has failed may you use the same object with `"status":"blocked"`.

## Informal statement

{item.informal_stmt}

## Informal proof (paper blueprint)

{item.informal_proof}
"""


def _task_file(item: RlmItem, max_compile_attempts: int) -> str:
    return f"""# RLM25 statement formalization task ({item.repo})

Translate only the natural-language theorem statement below into one Lean 4 theorem declaration.
Do not translate or produce a proof. The declaration's proof must remain exactly `:= by sorry`.
The declaration must be named `{item.name}`. `Context.lean` contains the exact Lean context
(imports, namespaces, prior declarations) under which your declaration is elaborated.
Do not add or repeat imports, `open` directives, namespaces, helpers, axioms, definitions, or a second declaration.
Edit only `Candidate.lean`. You may run `./check_candidate.sh` at most {max_compile_attempts} times.
Use only `./check_candidate.sh` for compilation; never invoke `lean` or `lake` directly.
Do not read, write, remove, or otherwise access `.compile_count`; the wrapper enforces the budget.
Do not inspect files outside this task directory and do not use the network.
When finished successfully, respond with exactly this JSON object and no extra keys:
`{{"candidate_path":"Candidate.lean","status":"completed"}}`
Do NOT respond before you have read this file and `Context.lean`, written your best attempt into
`Candidate.lean`, and run `./check_candidate.sh` at least once; an unattempted answer is a protocol
violation. Only after a real attempt has failed may you use the same object with `"status":"blocked"`.

## Natural-language statement

{item.informal_stmt}
"""


def _check_script(workspace: Path, item: RlmItem, max_compile_attempts: int, cache_home: Path, elan_home: Path, lean_bin: str = "", lean_path: str = "") -> str:
    return f"""#!/bin/sh
set -eu
count_file={shlex.quote(str(workspace / '.compile_count'))}
generated_dir={shlex.quote(str(workspace / '.generated'))}
context_file={shlex.quote(str(workspace / 'Context.lean'))}
candidate_file={shlex.quote(str(workspace / 'Candidate.lean'))}
combined_file={shlex.quote(str(workspace / '.generated' / 'Check.lean'))}
project_root={shlex.quote(item.project_dir)}
cache_home={shlex.quote(str(cache_home))}
elan_home={shlex.quote(str(elan_home))}

count=0
if [ -f "$count_file" ]; then
  count=$(/bin/cat "$count_file")
fi
if [ "$count" -ge {max_compile_attempts} ]; then
  echo "Compile budget exhausted ({max_compile_attempts})." >&2
  exit 64
fi
count=$((count + 1))
/bin/echo "$count" > "$count_file"
mkdir -p "$generated_dir"
full_context_file={shlex.quote(str(workspace / '.context-full.lean'))}
if [ -f "$full_context_file" ]; then
  ctx="$full_context_file"
else
  ctx="$context_file"
fi
{{ /bin/cat "$ctx"; /bin/echo; /bin/cat "$candidate_file"; }} > "$combined_file"
if [ -n "{shlex.quote(lean_bin)}" ]; then
  /usr/bin/env XDG_CACHE_HOME="$cache_home" GIT_CONFIG_GLOBAL=/dev/null LEAN_PATH={shlex.quote(lean_path)} {shlex.quote(lean_bin)} "$combined_file"
else
  /usr/bin/env XDG_CACHE_HOME="$cache_home" GIT_CONFIG_GLOBAL=/dev/null ELAN_HOME="$elan_home" PATH="$elan_home/bin:/usr/bin:/bin:/usr/sbin:/sbin" lake -d "$project_root" env lean "$combined_file"
fi
"""


def prepare_workspace(item: RlmItem, *, run_id: str, config: RunConfig, cache_home: Path, elan_home: Path, lean_bin: str = "", lean_path: str = "") -> Path:
    workspace_parent = config.workspaces_dir.resolve() / run_id
    workspace_parent.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        workspace = workspace_parent / f"task-{secrets.token_hex(16)}"
        try:
            workspace.mkdir()
            break
        except FileExistsError:
            continue
    else:
        raise RuntimeError("Unable to allocate a unique agent workspace")
    (workspace / ".generated").mkdir()
    (workspace / ".compile_count").write_text("0\n", encoding="ascii")
    if config.task == "proof-normal":
        (workspace / "Context.lean").write_text(item.context_normal, encoding="utf-8")
        (workspace / ".context-full.lean").write_text(item.context, encoding="utf-8")
        (workspace / "TASK.md").write_text(_task_file_proof(item, config.max_compile_attempts), encoding="utf-8")
        (workspace / "Candidate.lean").write_text(item.decl + "\n  sorry\n", encoding="utf-8")
    elif config.task == "proof":
        (workspace / "Context.lean").write_text(item.context, encoding="utf-8")
        (workspace / "TASK.md").write_text(_task_file_proof(item, config.max_compile_attempts), encoding="utf-8")
        (workspace / "Candidate.lean").write_text(item.decl + "\n  sorry\n", encoding="utf-8")
    else:
        (workspace / "Context.lean").write_text(item.context, encoding="utf-8")
        (workspace / "TASK.md").write_text(_task_file(item, config.max_compile_attempts), encoding="utf-8")
        (workspace / "Candidate.lean").write_text(
            f"theorem {item.name} : True := by sorry\n", encoding="utf-8"
        )
    script = workspace / "check_candidate.sh"
    script.write_text(
        _check_script(workspace, item, config.max_compile_attempts, cache_home, elan_home, lean_bin, lean_path),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    (workspace / "final.schema.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "candidate_path": {"type": "string", "const": "Candidate.lean"},
                    "status": {"type": "string", "enum": ["completed", "blocked"]},
                },
                "required": ["candidate_path", "status"],
            }
        ),
        encoding="utf-8",
    )
    return workspace


AGENT_PROMPT_STATEMENT = (
    "Read TASK.md and Context.lean. Formalize only the theorem statement by editing Candidate.lean. "
    "Keep the proof exactly `:= by sorry`. Use only ./check_candidate.sh for compiler feedback; never "
    "invoke lean or lake directly, and do not access .compile_count. Respect the compile budget and do "
    "not inspect outside this workspace. You MUST first read TASK.md and Context.lean, write your best "
    "formalization into Candidate.lean, and run ./check_candidate.sh at least once; responding without "
    "these steps is a protocol violation. Finish with exactly "
    '`{"candidate_path":"Candidate.lean","status":"completed"}` and no extra keys; use status '
    '`blocked` only after a real attempt has failed and you are genuinely unable to produce a '
    "compiling statement."
)


AGENT_PROMPT_PROOF = (
    "Read TASK.md and Context.lean. Candidate.lean already contains the target theorem with `:= by sorry`; "
    "replace the sorry with a complete tactic proof, keeping the theorem statement byte-identical. "
    "Use only ./check_candidate.sh for compiler feedback; never "
    "invoke lean or lake directly, and do not access .compile_count. Respect the compile budget and do "
    "not inspect outside this workspace. You MUST first read TASK.md and Context.lean, write your best "
    "proof into Candidate.lean, and run ./check_candidate.sh at least once; responding without "
    "these steps is a protocol violation. Finish with exactly "
    '`{"candidate_path":"Candidate.lean","status":"completed"}` and no extra keys; use status '
    '`blocked` only after a real attempt has failed and you are genuinely unable to produce a '
    "compiling proof."
)


async def _run_one(
    item: RlmItem,
    sample_id: int,
    run_id: str,
    config: RunConfig,
    generations_path: Path,
    cache_home: Path,
    elan_home: Path,
    write_lock: asyncio.Lock,
    semaphore: asyncio.Semaphore,
) -> None:
    try:
        lean_bin, lean_path = _resolve_lean_env(item.project_dir, elan_home)
    except (OSError, FileNotFoundError):
        lean_bin, lean_path = "", ""
    workspace = prepare_workspace(
        item, run_id=run_id, config=config, cache_home=cache_home, elan_home=elan_home, lean_bin=lean_bin, lean_path=lean_path
    )
    agent_prompt = (
        AGENT_PROMPT_PROOF if config.task in {"proof", "proof-normal"} else AGENT_PROMPT_STATEMENT
    )
    command = [
        config.codex_bin,
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "--skip-git-repo-check",
        "--color",
        "never",
        "--json",
        "--model",
        config.model,
        "--cd",
        str(workspace),
        "--output-schema",
        str(workspace / "final.schema.json"),
        "--config",
        'web_search="disabled"',
        "--config",
        'shell_environment_policy.inherit="none"',
        "--sandbox",
        "workspace-write",
    ]
    for feature in DISABLED_CODEX_FEATURES:
        command.extend(["--disable", feature])
    if config.reasoning_effort:
        command.extend(["--config", f'model_reasoning_effort="{config.reasoning_effort}"'])
    command.append("-")

    env = os.environ.copy()
    env["ELAN_HOME"] = str(elan_home)
    env["XDG_CACHE_HOME"] = str(cache_home)
    started_at = utc_now()
    started = time.monotonic()
    async with semaphore:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(agent_prompt.encode("utf-8")), timeout=config.timeout_seconds
            )
            termination = None
        except asyncio.TimeoutError:
            try:
                os.killpg(os.getpgid(process.pid), 15)
            except (ProcessLookupError, PermissionError):
                process.kill()
            stdout, stderr = await process.communicate()
            termination = "timeout"
    wall_ms = int((time.monotonic() - started) * 1000)
    status = (
        "agent_timeout"
        if termination == "timeout"
        else ("ok" if process.returncode == 0 else "agent_error")
    )
    logs_dir = generations_path.parent.resolve() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(16)
    (logs_dir / f"{token}.events.jsonl").write_bytes(stdout[:MAX_STDOUT_BYTES])
    (logs_dir / f"{token}.stderr.log").write_bytes(stderr[-65536:])
    try:
        raw_text = (workspace / "Candidate.lean").read_text(encoding="utf-8")
        if len(raw_text.encode("utf-8")) > MAX_CANDIDATE_BYTES:
            raw_text = ""
            output_truncated = True
        else:
            output_truncated = False
    except (OSError, UnicodeError):
        raw_text = ""
        output_truncated = True
    compile_attempts = 0
    try:
        compile_attempts = int((workspace / ".compile_count").read_text().strip() or 0)
    except (OSError, ValueError):
        pass
    final_message = None
    for raw_line in stdout.decode("utf-8", errors="replace").splitlines():
        if raw_line.strip().startswith("{\"type\":"):
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "item.completed" and event.get("item", {}).get("type") == "agent_message":
                final_message = event["item"].get("text")
    record = {
        "run_id": run_id,
        "track": "codex_agent",
        "item_index": item.index,
        "item_name": item.label,
        "item_repo": item.repo,
        "sample_id": sample_id,
        "model": config.model,
        "status": status,
        "exit_code": process.returncode,
        "termination_reason": termination,
        "started_at": started_at,
        "finished_at": utc_now(),
        "wall_ms": wall_ms,
        "workspace": str(workspace),
        "events_path": str(logs_dir / f"{token}.events.jsonl"),
        "compile_attempts": compile_attempts,
        "output_truncated": output_truncated,
        "raw_text": raw_text,
        "agent_final_message": final_message,
    }
    async with write_lock:
        with generations_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


async def run_codex(
    items: list[RlmItem],
    run_id: str,
    config: RunConfig,
    cache_home: Path,
    elan_home: Path,
) -> Path:
    generations_path = config.artifacts_dir.resolve() / run_id / "generations.jsonl"
    generations_path.parent.mkdir(parents=True, exist_ok=True)
    if generations_path.exists():
        raise FileExistsError(f"{generations_path} already exists; choose a new --run-id")
    write_lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(config.concurrency)
    await asyncio.gather(
        *(
            _run_one(item, sample_id, run_id, config, generations_path, cache_home, elan_home, write_lock, semaphore)
            for item in items
            for sample_id in range(config.samples)
        )
    )
    return generations_path
```

### D.3 src/rlm_agent/scoring.py

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from lean_interact import AutoLeanServer, LeanREPLConfig, LocalProject
from lean_interact.interface import Command, LeanError
from lean_interact.utils import clean_theorem_string

from rlm_eval.metrics.beq_plus import check_theorem_equivalence


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_candidate(raw_text: str, *, theorem_name: str) -> tuple[str | None, str | None]:
    """Fail closed: candidate must be a single theorem declaration; proof is replaced by sorry."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("lean"):
            text = text[4:]
        text = text.strip()
    normalized = clean_theorem_string(text, new_theorem_name=theorem_name, add_sorry=True)
    if normalized is None:
        return None, "theorem_extraction_failed"
    return normalized, None


class RepoScorer:
    """One Lean REPL per project directory; mirrors RLMEval _process_predictions semantics."""

    def __init__(self) -> None:
        self._servers: dict[str, AutoLeanServer] = {}


    def score_proof(self, record: dict, item, *, timeout_context: int = 900, timeout_per_proof: int = 300) -> dict:
        """RLMEval proof track: grade = gold statement + candidate proof compiles with allow_sorry=False."""
        import re as _re

        result = {
            "run_id": record.get("run_id"),
            "track": record.get("track"),
            "item_index": int(record["item_index"]),
            "item_name": record.get("item_name"),
            "item_repo": record.get("item_repo"),
            "sample_id": int(record.get("sample_id", 0)),
            "model": record.get("model"),
            "generation_status": record.get("status"),
            "scored_at": utc_now(),
            "parse_ok": False,
            "proof_ok": False,
        }
        if record.get("status") not in {"ok", "completed"}:
            result["score_status"] = "generation_error"
            return result
        raw = (record.get("raw_text") or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("lean"):
                raw = raw[4:]
            raw = raw.strip()
        if not raw:
            result["score_status"] = "parse_error"
            return result
        result["parse_ok"] = True
        # upstream fast-fail placeholders
        for bad in ("sorry", "admit", "apply?"):
            if bad in raw:
                result["score_status"] = "placeholder_in_proof"
                return result
        # dojo declsig itself includes the original doc-comment; strip leading comments on BOTH sides
        strip_comments = lambda s: _re.sub(r"^(\s*--[^\n]*\n)+\s*", "", _re.sub(r"^\s*/--[\s\S]*?-/\s*", "", s.strip())).strip()
        raw = strip_comments(raw)
        decl_core = strip_comments(item.decl)
        # statement must remain unchanged: compare on the declsig only (without ":= by"),
        # so term-mode proofs (":= <term>") are accepted like tactic-mode ones
        declsig_core = _re.sub(r"\s*:=\s*by\s*$", "", decl_core).strip()
        norm = lambda s: _re.sub(r"\s+", " ", s).strip()
        if not norm(raw).startswith(norm(declsig_core)):
            result["score_status"] = "statement_modified"
            result["error"] = "candidate does not start with the gold theorem declaration"
            return result
        proof_body = _extract_proof_after_decl(raw, decl_core)
        server = self.server(item.project_dir)
        try:
            ctx_out = server.run(Command(cmd=item.context), add_to_session_cache=True, timeout=timeout_context)
            if isinstance(ctx_out, LeanError) or not ctx_out.lean_code_is_valid():
                result["score_status"] = "context_error"
                result["error"] = str(ctx_out)[:2000]
                return result
            context_env = ctx_out.env
            code = raw
            out = server.run(Command(cmd=code, env=context_env), timeout=timeout_per_proof)
            if isinstance(out, LeanError):
                result["score_status"] = "proof_lean_error"
                result["typecheck_error"] = str(out)[:2000]
                return result
            result["proof_ok"] = out.lean_code_is_valid(allow_sorry=False)
            result["typecheck_ok"] = result["proof_ok"]
            if not result["proof_ok"]:
                result["typecheck_error"] = str(out)[:2000]
            result["score_status"] = "passed" if result["proof_ok"] else "failed"
        except Exception as exc:  # noqa: BLE001
            result["score_status"] = "checker_error"
            result["error"] = f"{type(exc).__name__}:{exc}"[:2000]
        return result

    def server(self, project_dir: str) -> AutoLeanServer:
        if project_dir not in self._servers:
            self._servers[project_dir] = AutoLeanServer(LeanREPLConfig(project=LocalProject(project_dir)))
        return self._servers[project_dir]

    def score(self, record: dict, item, *, task: str = "statement", timeout_context: int = 360, timeout_per_proof: int = 120) -> dict:
        if task in {"proof", "proof-normal"}:
            return self.score_proof(record, item, timeout_context=timeout_context, timeout_per_proof=timeout_per_proof)
        result = {
            "run_id": record.get("run_id"),
            "track": record.get("track"),
            "item_index": int(record["item_index"]),
            "item_name": record.get("item_name"),
            "item_repo": record.get("item_repo"),
            "sample_id": int(record.get("sample_id", 0)),
            "model": record.get("model"),
            "generation_status": record.get("status"),
            "scored_at": utc_now(),
            "parse_ok": False,
            "typecheck_ok": False,
            "beq_plus_ok": False,
        }
        if record.get("status") not in {"ok", "completed"}:
            result["score_status"] = "generation_error"
            return result
        candidate, norm_error = normalize_candidate(record.get("raw_text") or "", theorem_name=item.name)
        if candidate is None:
            result["score_status"] = "parse_error"
            result["parse_error"] = norm_error
            return result
        result["candidate_lean"] = candidate
        result["parse_ok"] = True
        server = self.server(item.project_dir)
        try:
            ctx_out = server.run(Command(cmd=item.context), add_to_session_cache=True, timeout=timeout_context)
            if isinstance(ctx_out, LeanError) or not ctx_out.lean_code_is_valid():
                result["score_status"] = "context_error"
                result["error"] = str(ctx_out)[:2000]
                return result
            context_env = ctx_out.env
            gt_out = server.run(Command(cmd=item.formal_stmt, env=context_env), timeout=timeout_per_proof)
            if isinstance(gt_out, LeanError) or not gt_out.lean_code_is_valid():
                result["score_status"] = "reference_error"
                result["error"] = str(gt_out)[:2000]
                return result
            cand_out = server.run(Command(cmd=candidate, env=context_env), timeout=timeout_per_proof)
            if isinstance(cand_out, LeanError):
                result["score_status"] = "candidate_lean_error"
                result["typecheck_error"] = str(cand_out)[:2000]
                return result
            result["typecheck_ok"] = cand_out.lean_code_is_valid(allow_sorry=True)
            if not result["typecheck_ok"]:
                result["score_status"] = "typecheck_error"
                result["typecheck_error"] = str(cand_out)[:2000]
                return result
            beq = check_theorem_equivalence(
                theorem1=candidate,
                theorem2=item.formal_stmt,
                lean_server=server,
                context_env=context_env,
                timeout_per_proof=timeout_per_proof,
            )
            result["beq_plus_ok"] = bool(beq.beq_plus())
            result["beql_ok"] = bool(beq.beql())
            result["score_status"] = "certified" if result["beq_plus_ok"] else "not_certified"
        except Exception as exc:  # noqa: BLE001
            result["score_status"] = "checker_error"
            result["error"] = f"{type(exc).__name__}:{exc}"[:2000]
        return result


def score_records(records: list[dict], items: dict, output_path: Path, task: str = "statement") -> dict:
    scorer = RepoScorer()
    counts: dict[str, int] = {}
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            item = items[int(record["item_index"])]
            row = scorer.score(record, item, task=task)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            counts[row["score_status"]] = counts.get(row["score_status"], 0) + 1
            ok = row.get("beq_plus_ok", row.get("proof_ok"))
            print(f"[{row['item_index']}] {row['item_name']}: {row['score_status']} ok={ok}", flush=True)
    return counts


def indent_proof(proof_body: str) -> str:
    """Fix first tactic indentation like upstream fix_first_tactic_indentation."""
    lines = proof_body.splitlines()
    if not lines:
        return ""
    min_indent = None
    for idx in range(1, len(lines)):
        if lines[idx].strip():
            ind = len(lines[idx]) - len(lines[idx].lstrip())
            min_indent = ind if min_indent is None else min(min_indent, ind)
    if min_indent is None:
        return "  " + lines[0].strip() + "\n"
    fixed = [" " * min_indent + lines[0].lstrip()]
    return "\n".join(fixed + lines[1:]) + "\n"


def _extract_proof_after_decl(raw: str, decl: str) -> str:
    """Return everything after the ':= by' that ends the (comment-stripped) gold decl."""
    norm = __import__("re").sub(r"\s+", " ", raw.strip())
    decl_norm = __import__("re").sub(r"\s+", " ", decl.strip())
    if norm.startswith(decl_norm):
        raw_rest = raw.strip()[len(decl.rstrip()):]
    else:
        idx = raw.find(":= by")
        raw_rest = raw[idx + len(":= by"):] if idx >= 0 else raw
    return raw_rest
```

### D.4 src/rlm_agent/cli.py

```python
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .items import build_items, load_items, parse_indices

DEFAULT_DATASET = Path(__file__).resolve().parents[2] / "data" / "rlm25_pfr_tlb.jsonl"


def _cmd_items(args: argparse.Namespace) -> None:
    override = {}
    if args.project_map:
        for pair in args.project_map.split(","):
            name, path = pair.split("=", 1)
            override[name] = path
    items = build_items(Path(args.config), project_override=override or None)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item.to_row(), ensure_ascii=False) + "\n")
    per_repo = Counter(item.repo for item in items)
    print(f"wrote {len(items)} items to {out}: {dict(per_repo)}")


def _cmd_run_codex(args: argparse.Namespace) -> None:
    items_map = load_items(Path(args.dataset))
    indices = parse_indices(args.indices, list(items_map))
    from .runner import RunConfig, run_codex
    import asyncio

    config = RunConfig(
        task=args.task,
        model=args.model,
        codex_bin=args.codex_bin,
        timeout_seconds=args.timeout_seconds,
        max_compile_attempts=args.max_compile_attempts,
        reasoning_effort=args.reasoning_effort,
        artifacts_dir=Path(args.artifacts_dir).resolve(),
        workspaces_dir=Path(args.workspaces_dir).resolve(),
        concurrency=args.concurrency,
        samples=args.samples,
    )
    generations = asyncio.run(
        run_codex(
            [items_map[i] for i in indices],
            args.run_id,
            config,
            cache_home=Path(args.cache_dir),
            elan_home=Path(args.elan_home),
        )
    )
    print(f"generations: {generations}")


def _cmd_score(args: argparse.Namespace) -> None:
    items_map = load_items(Path(args.dataset))
    records = [json.loads(line) for line in Path(args.input).read_text(encoding="utf-8").splitlines() if line.strip()]
    from .scoring import score_records

    counts = score_records(records, items_map, Path(args.output), task=args.task)
    total = sum(counts.values())
    certified = counts.get("certified", 0) + counts.get("passed", 0)
    print(f"summary: {counts}")
    if total:
        print(f"pass rate: {certified}/{total} = {certified / total:.1%}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rlmv-eval", description="RLM25 codex-agent statement formalization")
    sub = parser.add_subparsers(dest="cmd", required=True)

    items_cmd = sub.add_parser("items", help="Build the item dataset from traced_repos")
    items_cmd.add_argument("--config", required=True)
    items_cmd.add_argument("--out", default=str(DEFAULT_DATASET))
    items_cmd.add_argument("--project-map", default="", help="e.g. PFR=/data/.../pfr,TLB=/data/.../tlb")
    items_cmd.set_defaults(func=_cmd_items)

    run_cmd = sub.add_parser("run-codex", help="Run codex agent generation (ProofNet-Verified protocol)")
    run_cmd.add_argument("--model", required=True)
    run_cmd.add_argument("--dataset", default=str(DEFAULT_DATASET))
    run_cmd.add_argument("--indices", required=True, help="e.g. 1,2,3 or all")
    run_cmd.add_argument("--samples", type=int, default=1)
    run_cmd.add_argument("--concurrency", type=int, default=1)
    run_cmd.add_argument("--timeout-seconds", type=int, default=900)
    run_cmd.add_argument("--max-compile-attempts", type=int, default=3)
    run_cmd.add_argument("--reasoning-effort", default=None)
    run_cmd.add_argument("--task", choices=["statement", "proof", "proof-normal"], default="statement")
    run_cmd.add_argument("--run-id", required=True)
    run_cmd.add_argument("--artifacts-dir", default="artifacts")
    run_cmd.add_argument("--workspaces-dir", default="agent_workspaces")
    run_cmd.add_argument("--codex-bin", default="codex")
    run_cmd.add_argument("--elan-home", default="/data/projects/math-harness-eval/elan")
    run_cmd.add_argument("--cache-dir", default=".rlm-cache")
    run_cmd.set_defaults(func=_cmd_run_codex)

    score_cmd = sub.add_parser("score", help="Typecheck + BEq+ against ground truth")
    score_cmd.add_argument("--dataset", default=str(DEFAULT_DATASET))
    score_cmd.add_argument("--input", required=True)
    score_cmd.add_argument("--output", required=True)
    score_cmd.add_argument("--task", choices=["statement", "proof", "proof-normal"], default="statement")
    score_cmd.set_defaults(func=_cmd_score)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### D.5 rlmv-eval

```bash
#!/usr/bin/env bash
exec /data/projects/math-harness-eval/RLMEval//root/miniconda3/envs/rlmeval/bin/python -m rlm_agent.cli "$@"
```

### D.6 scripts/run-glm-smoke.sh

```bash
#!/usr/bin/env bash
# GLM-5.3 (lhcodex) codex-agent smoke on RLM25 PFR+TLB — ProofNet-Verified protocol
set -euo pipefail
cd /data/projects/math-harness-eval/RLMEval
export HOME=/data/projects/math-harness-eval/rlm-env/home
export XDG_CACHE_HOME=$HOME/.cache
export ELAN_HOME=${ELAN_HOME:-/data/projects/math-harness-eval/elan}
RUN_ID=${RUN_ID:-glm53-codex-smoke-$(date +%Y%m%d-%H%M%S)}
TASK=${TASK:-statement}
MODEL=${MODEL:-glm-5.3}
CODEX_WRAPPER=${CODEX_WRAPPER:-run-logs/codex-glm-lhcodex}
INDICES=${INDICES:-1,2,3}

./rlmv-eval items \
  --config configs/benchmark/pfr_tlb.yaml \
  --out data/rlm25_pfr_tlb.jsonl \
  --project-map "PFR=/data/projects/math-harness-eval/rlm-env/pfr,TLB=/data/projects/math-harness-eval/rlm-env/tlb"

echo "[$(date -Is)] generation start: $RUN_ID task=$TASK indices=$INDICES"
./rlmv-eval run-codex \
  --model "$MODEL" \
  --dataset data/rlm25_pfr_tlb.jsonl \
  --indices "$INDICES" \
  --samples 1 --concurrency 3 --timeout-seconds ${TMO:-1500} --max-compile-attempts 3 \
  --reasoning-effort xhigh \
  --task "$TASK" \
  --artifacts-dir artifacts \
  --workspaces-dir agent_workspaces \
  --codex-bin "$CODEX_WRAPPER" \
  --elan-home "$ELAN_HOME" \
  --cache-dir .rlm-cache \
  --run-id "$RUN_ID"
echo "[$(date -Is)] scoring start"
./rlmv-eval score \
  --dataset data/rlm25_pfr_tlb.jsonl \
  --input "artifacts/$RUN_ID/generations.jsonl" \
  --output "artifacts/$RUN_ID/scores.jsonl" \
  --task "$TASK"
echo "[$(date -Is)] smoke complete: artifacts/$RUN_ID"
```

### D.7 scripts/run-glm-proof-full.sh（已移至 scripts/legacy/）

```bash
#!/usr/bin/env bash
# GLM-5.3 (lhcodex) codex-agent FULL run on RLM25 PFR+TLB proof track (Easy mode)
set -euo pipefail
cd /data/projects/math-harness-eval/RLMEval
export HOME=/data/projects/math-harness-eval/rlm-env/home
export XDG_CACHE_HOME=$HOME/.cache
export ELAN_HOME=/data/projects/math-harness-eval/elan
RUN_ID=${RUN_ID:-glm53-codex-proof-full-$(date +%Y%m%d-%H%M%S)}
INDICES=${INDICES:-1,2,3,4,5,6,8,9,10,11,12,13,14,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,88,89,91,92,98,99,100,101,102,103,104,105,108,116,117,118,119,120,121,122,123,124,125,126,127,128,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,156,159,161,163,164,165,168,169,170,171,172,173,176,177,179,180,181,182,183,184,185,187,188,189,190,191,192,193,194,196,199,200,201,202,203,204,205,206,207,208,209,210,211,212,213,214,215,216,217,219,220,221,222,223,227,228,229,230,231,232,235,236,237,238,243,244,245,246,248,249,250,251,252,253,254,255,256,257,259,260,264,265,266,267,268,269}
CONC=${CONC:-4}

echo "[$(date -Is)] proof-full start: $RUN_ID items=$(echo $INDICES | tr ',' '\n' | wc -l) conc=$CONC"
./rlmv-eval run-codex \
  --model glm-5.3 \
  --dataset data/rlm25_pfr_tlb.jsonl \
  --indices "$INDICES" \
  --task proof \
  --samples 1 --concurrency "$CONC" --timeout-seconds 2400 --max-compile-attempts 3 \
  --reasoning-effort xhigh \
  --artifacts-dir artifacts \
  --workspaces-dir agent_workspaces \
  --codex-bin run-logs/codex-glm-lhcodex \
  --elan-home "$ELAN_HOME" \
  --cache-dir .rlm-cache \
  --run-id "$RUN_ID"
echo "[$(date -Is)] generation done, scoring start"
./rlmv-eval score \
  --dataset data/rlm25_pfr_tlb.jsonl \
  --input "artifacts/$RUN_ID/generations.jsonl" \
  --output "artifacts/$RUN_ID/scores.jsonl" \
  --task proof
echo "[$(date -Is)] complete: $RUN_ID"
```

## 附录 E：端点与沙箱组件

### E.1 run-logs/codex-glm-lhcodex

```bash
#!/usr/bin/env bash
set -euo pipefail
export GLM_API_KEY='sk-40ebc71f6ff47830e3fb59c8b6122da12997e18b009783b55707a2235fb9a720'
# lhcodex is external: keep default proxy env (http://httpproxy-headless...:3128) so codex can reach it
CODEX=${CODEX_BIN:-/usr/local/bin/codex}
if [ "${1:-}" = "--version" ]; then exec "$CODEX" "$@"; fi
if [ "${1:-}" = "exec" ]; then
  shift
  exec "$CODEX" exec \
    --config 'model_provider="glm53"' \
    --config 'model_providers.glm53.name="GLM 5.3 via lhcodex"' \
    --config 'model_providers.glm53.base_url="https://lhcodex.zeabur.app/v1"' \
    --config 'model_providers.glm53.env_key="GLM_API_KEY"' \
    --config 'model_providers.glm53.wire_api="responses"' \
    --config 'model_providers.glm53.requires_openai_auth=false' \
    --config 'shell_environment_policy.set.PATH="/data/projects/math-harness-eval/RLMEval/run-logs/bin:/usr/local/bin:/usr/bin:/bin"' \
    "$@"
fi
exec "$CODEX" "$@"
```

### E.2 run-logs/codex-ds-internal

```bash
#!/usr/bin/env bash
set -euo pipefail
export DS_API_KEY='dummy'
export NO_PROXY='127.0.0.1,localhost,::1,s-20261015140447-hc45n.ailab-ma4agismall.pjh-service.org.cn'
export no_proxy="$NO_PROXY"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
CODEX=${CODEX_BIN:-/usr/local/bin/codex}
if [ "${1:-}" = "--version" ]; then exec "$CODEX" "$@"; fi
if [ "${1:-}" = "exec" ]; then
  shift
  exec "$CODEX" exec \
    --config 'model_provider="dsv4p"' \
    --config 'model_providers.dsv4p.name="DS v4 Pro (internal hc45n)"' \
    --config 'model_providers.dsv4p.base_url="http://127.0.0.1:4102/v1"' \
    --config 'model_providers.dsv4p.env_key="DS_API_KEY"' \
    --config 'model_providers.dsv4p.wire_api="responses"' \
    --config 'model_providers.dsv4p.requires_openai_auth=false' \
    --config 'shell_environment_policy.set.PATH="/data/projects/math-harness-eval/RLMEval/run-logs/bin:/usr/local/bin:/usr/bin:/bin"' \
    "$@"
fi
exec "$CODEX" "$@"
```

### E.3 run-logs/ds-responses-fix-proxy.py

```python
"""清洗代理:把 sglang /v1/responses SSE 流里的 "created_at":<float> 改成整数,
codex 0.158 的 serde 拒收浮点 unix 时间戳导致 "error decoding response body"。
监听 127.0.0.1:4102 → 转发 DS 内网端点,SSE 其余内容逐字节透传。"""
import json
import re
from aiohttp import web, ClientSession

UPSTREAM = "http://s-20261015140447-hc45n.ailab-ma4agismall.pjh-service.org.cn"
FLOAT_INT = re.compile(rb'"(created_at|sequence_number|input_tokens|output_tokens|total_tokens|created)":(\d+)\.0+\b')


def clean(chunk: bytes) -> bytes:
    return FLOAT_INT.sub(rb'"\1":\2', chunk)


async def forward(request: web.Request) -> web.StreamResponse:
    raw = await request.read()
    if request.path.startswith("/v1/responses"):
        # sglang dies mid-stream on reasoning.summary / encrypted_content includes
        try:
            body = json.loads(raw)
            changed = False
            if "reasoning" in body:
                body.pop("reasoning")
                changed = True
            inc = body.get("include")
            if isinstance(inc, list):
                filtered = [x for x in inc if not str(x).startswith("reasoning.")]
                if len(filtered) != len(inc):
                    body["include"] = filtered
                    changed = True
            if changed:
                raw = json.dumps(body).encode()
        except Exception:
            pass
    headers = {"Content-Type": "application/json"}
    if "Authorization" in request.headers:
        headers["Authorization"] = request.headers["Authorization"]
    session: ClientSession = request.app["client"]
    upstream = await session.post(
        f"{UPSTREAM}{request.path_qs}", data=raw, headers=headers
    )
    resp = web.StreamResponse(status=upstream.status, headers={
        "Content-Type": upstream.headers.get("Content-Type", "application/json"),
        "Cache-Control": "no-cache",
    })
    await resp.prepare(request)
    dump = None
    if request.path.startswith("/v1/responses"):
        import time as _t
        dump = open(f"/tmp/ds-dump-{_t.time():.0f}.txt", "wb")
    try:
        if "text/event-stream" in upstream.headers.get("Content-Type", ""):
            async for chunk in upstream.content.iter_any():
                if dump is not None:
                    dump.write(chunk)
                await resp.write(clean(chunk))
        else:
            async for chunk in upstream.content.iter_any():
                if dump is not None:
                    dump.write(chunk)
                await resp.write(chunk)
    finally:
        if dump is not None:
            dump.close()
    await resp.write_eof()
    return resp


async def on_startup(app: web.Application):
    app["client"] = ClientSession()


async def on_cleanup(app: web.Application):
    await app["client"].close()


app = web.Application()
app.router.add_route("*", "/{tail:.*}", forward)
app.on_startup.append(on_startup)
app.on_cleanup.append(on_cleanup)

if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=4102, print=None)
```

### E.4 run-logs/bin/apply_patch

```python
#!/usr/bin/env python3
"""Minimal apply_patch implementation (codex patch protocol).

Supports *** Begin Patch / *** Update File / *** Add File / *** Delete File
with *** End Patch, hunks introduced by @@, context lines, +/- changes and
*** Move to: renaming. Fails non-zero on any mismatch without writing files.
"""
import sys
from pathlib import Path


def parse(text: str):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "*** Begin Patch":
        raise SystemExit("apply_patch: missing *** Begin Patch")
    ops = []
    i = 1
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s == "*** End Patch":
            break
        if s.startswith("*** Update File: "):
            path = s[len("*** Update File: "):]
            i += 1
            move_to = None
            if i < len(lines) and lines[i].strip().startswith("*** Move to: "):
                move_to = lines[i].strip()[len("*** Move to: "):]
                i += 1
            hunks, i = parse_hunks(lines, i)
            ops.append(("update", path, move_to, hunks))
        elif s.startswith("*** Add File: "):
            path = s[len("*** Add File: "):]
            i += 1
            body = []
            while i < len(lines) and not lines[i].startswith("***"):
                body.append(lines[i][1:] if lines[i].startswith("+") else lines[i])
                i += 1
            ops.append(("add", path, None, body))
        elif s.startswith("*** Delete File: "):
            ops.append(("delete", s[len("*** Delete File: "):], None, None))
            i += 1
        else:
            raise SystemExit(f"apply_patch: unexpected line: {line!r}")
    return ops


def parse_hunks(lines, i):
    hunks = []
    cur = []
    while i < len(lines):
        line = lines[i]
        if line.startswith("***"):
            break
        if line.startswith("@@"):
            if cur:
                hunks.append(cur)
            cur = []
        else:
            cur.append(line)
        i += 1
    if cur:
        hunks.append(cur)
    return hunks, i


def apply_hunks(old_lines, hunks):
    new_lines = list(old_lines)
    offset = 0
    for hunk in hunks:
        ctx = [l[1:] if l[:1] in "+-" else l for l in hunk if not l.startswith("@@")]
        pre = [l[1:] for l in hunk if l.startswith(" ")]
        # locate by the combined context (before + after)
        wanted = [l[1:] for l in hunk if l.startswith(" ") or l.startswith("-")]
        if not wanted:
            raise SystemExit("apply_patch: hunk without context")
        pos = find_sub(new_lines, wanted, offset)
        if pos is None:
            pos = find_sub(new_lines, wanted, 0)
        if pos is None:
            raise SystemExit("apply_patch: context not found")
        replaced = [l[1:] for l in hunk if not l.startswith("-")]
        new_lines[pos : pos + len(wanted)] = replaced
        offset = pos + len(replaced)
    return new_lines


def find_sub(hay, needle, start):
    n = len(needle)
    for i in range(start, len(hay) - n + 1):
        if hay[i : i + n] == needle:
            return i
    return None


def main():
    text = sys.stdin.read()
    ops = parse(text)
    for op, path, move_to, payload in ops:
        p = Path(path)
        if op == "add":
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("\n".join(payload) + "\n")
            print(f"apply_patch: added {path}")
        elif op == "delete":
            p.unlink(missing_ok=True)
            print(f"apply_patch: deleted {path}")
        else:
            old = p.read_text().splitlines()
            new = apply_hunks(old, payload)
            target = Path(move_to) if move_to else p
            if move_to:
                p.unlink()
            target.write_text("\n".join(new) + "\n")
            print(f"apply_patch: updated {path}" + (f" -> {move_to}" if move_to else ""))


if __name__ == "__main__":
    main()
```

### E.5 configs/benchmark/pfr_tlb.yaml

```yaml
repositories:
  - git_url: "/data/projects/math-harness-eval/rlm-env/pfr-src"
    commit: "f6bdcac2365623d3667d3ff8fd8ddb7f95ce2313"
    project_name: "PFR"
    blueprint_cmd: null
  - git_url: "/data/projects/math-harness-eval/rlm-env/tlb-src"
    commit: "0f09ff100a06a5e4542181514bfff74213ae126b"
    project_name: "TLB"
    blueprint_cmd: null
```
