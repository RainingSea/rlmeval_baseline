from __future__ import annotations

import asyncio
import json
import os
import secrets
import shlex
import stat
import time
import urllib.error
import urllib.request
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
    use_output_schema: bool = True
    api_base: str = ""
    api_key: str = ""
    max_tokens: int | None = None
    stream: bool = True


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
        "--config",
        'web_search="disabled"',
        "--config",
        'shell_environment_policy.inherit="none"',
        "--sandbox",
        "workspace-write",
    ]
    for feature in DISABLED_CODEX_FEATURES:
        command.extend(["--disable", feature])
    # Some OpenAI-compatible backends (e.g. sglang) apply the Responses API
    # text.format json_schema constraint to the whole generation, which blocks
    # tool calls entirely; the final-JSON contract is already in the prompt.
    if config.use_output_schema:
        command.extend(["--output-schema", str(workspace / "final.schema.json")])
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
            communicate = process.communicate(agent_prompt.encode("utf-8"))
            if config.timeout_seconds > 0:
                stdout, stderr = await asyncio.wait_for(communicate, timeout=config.timeout_seconds)
            else:
                stdout, stderr = await communicate
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


# Direct single-shot track: no codex harness, one chat/completions call per sample.
# The agent prompt is reused verbatim; workspace files are inlined because the
# bare model has no filesystem or tool access.

_DIRECT_SUFFIX_TEMPLATE = """

This is a single-shot evaluation: you have no filesystem, shell, or tool access.
The workspace files referenced above are provided inline below.

===== TASK.md =====
{task_md}

===== Context.lean =====
{context}

===== Candidate.lean (current) =====
{candidate}

Respond with the complete final content of Candidate.lean as a single ```lean fenced
code block, and nothing else. Do not restate the context."""


# Internal endpoints must not go through http_proxy (mirrors scripts/run-sglang-experiment.sh).
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _blocking_completion(config: RunConfig, request: urllib.request.Request, live_path: Path | None) -> dict:
    """Non-streaming chat/completions; one blocking POST, full body in one response."""
    started = time.monotonic()
    with _NO_PROXY_OPENER.open(request, timeout=config.timeout_seconds or None) as response:
        result = json.loads(response.read().decode("utf-8"))
    elapsed = time.monotonic() - started
    message = ((result.get("choices") or [{}])[0].get("message")) or {}
    content = message.get("content") or ""
    reasoning = message.get("reasoning_content") or ""
    if live_path is not None:
        with live_path.open("a", encoding="utf-8", errors="replace") as live_file:
            live_file.write(f"[{time.strftime('%H:%M:%S')}] model={config.model} "
                            f"reasoning_effort={config.reasoning_effort or 'off'} "
                            f"max_tokens={config.max_tokens or 'unset'} stream=off (blocking)\n")
            if reasoning:
                live_file.write("<think>\n" + reasoning + "\n</think>\n")
            live_file.write(content)
            live_file.write(f"\n\n[{time.strftime('%H:%M:%S')}] response end (blocking)\n")
    result["_stream_stats"] = {
        "mode": "blocking",
        "elapsed_s": round(elapsed, 1),
        "content_chars": len(content),
        "reasoning_chars": len(reasoning),
    }
    return result


def _chat_completion(config: RunConfig, prompt: str, live_path: Path | None = None) -> dict:
    """chat/completions; aggregates streaming SSE deltas into a non-streaming-shaped dict.

    If live_path is set, output is appended as it arrives (reasoning wrapped in
    <think>...</think>) so the generation can be watched with `tail -f`.
    Stream stats (first-token latency, chunk timeline) are attached under
    "_stream_stats" for diagnostics. In streaming mode the urlopen timeout acts as
    an inter-chunk liveness timeout; total wall time stays bounded by the outer
    asyncio timeout.
    """
    payload = {
        "model": config.model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if config.max_tokens:
        payload["max_tokens"] = config.max_tokens
    if config.reasoning_effort:
        payload["reasoning_effort"] = config.reasoning_effort
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.api_key}",
    }
    if config.stream:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        headers["Accept"] = "text/event-stream"
    request = urllib.request.Request(
        config.api_base.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    if not config.stream:
        return _blocking_completion(config, request, live_path)
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    finish_reason = None
    usage = None
    response_id = None
    chunk_times: list[float] = []
    started = time.monotonic()
    live_file = live_path.open("a", encoding="utf-8", errors="replace") if live_path else None
    in_think = False
    try:
        if live_file is not None:
            live_file.write(f"[{time.strftime('%H:%M:%S')}] model={config.model} "
                            f"reasoning_effort={config.reasoning_effort or 'off'} "
                            f"max_tokens={config.max_tokens or 'unset'}\n")
        with _NO_PROXY_OPENER.open(request, timeout=60) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if response_id is None:
                    response_id = chunk.get("id")
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
                delta = choice.get("delta") or {}
                got_text = False
                if delta.get("reasoning_content"):
                    if live_file is not None and not in_think:
                        live_file.write("<think>\n")
                        in_think = True
                    reasoning_parts.append(delta["reasoning_content"])
                    if live_file is not None:
                        live_file.write(delta["reasoning_content"])
                        live_file.flush()
                    got_text = True
                if delta.get("content"):
                    if live_file is not None and in_think:
                        live_file.write("\n</think>\n")
                        in_think = False
                    content_parts.append(delta["content"])
                    if live_file is not None:
                        live_file.write(delta["content"])
                        live_file.flush()
                    got_text = True
                if got_text:
                    chunk_times.append(time.monotonic() - started)
    finally:
        if live_file is not None:
            if in_think:
                live_file.write("\n</think>\n")
            live_file.write(f"\n\n[{time.strftime('%H:%M:%S')}] stream end, finish_reason={finish_reason}\n")
            live_file.close()
    elapsed = time.monotonic() - started
    return {
        "id": response_id,
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {
                    "role": "assistant",
                    "content": "".join(content_parts),
                    "reasoning_content": "".join(reasoning_parts),
                },
            }
        ],
        "usage": usage,
        "_stream_stats": {
            "elapsed_s": round(elapsed, 1),
            "chunks": len(chunk_times),
            "first_token_s": round(chunk_times[0], 2) if chunk_times else None,
            "content_chars": sum(len(p) for p in content_parts),
            "reasoning_chars": sum(len(p) for p in reasoning_parts),
        },
    }


async def _run_one_direct(
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
    prompt = agent_prompt + _DIRECT_SUFFIX_TEMPLATE.format(
        task_md=(workspace / "TASK.md").read_text(encoding="utf-8"),
        context=(workspace / "Context.lean").read_text(encoding="utf-8"),
        candidate=(workspace / "Candidate.lean").read_text(encoding="utf-8"),
    )
    started_at = utc_now()
    started = time.monotonic()
    logs_dir = generations_path.parent.resolve() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(16)
    live_path = logs_dir / f"{token}.stream.log"
    response: dict | None = None
    termination = None
    error_detail = ""
    async with semaphore:
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(_chat_completion, config, prompt, live_path),
                timeout=config.timeout_seconds if config.timeout_seconds > 0 else None,
            )
        except asyncio.TimeoutError:
            termination = "timeout"
        except urllib.error.HTTPError as exc:
            error_detail = f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:2000]}"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            error_detail = f"{type(exc).__name__}: {exc}"
    wall_ms = int((time.monotonic() - started) * 1000)
    raw_text = ""
    final_message = None
    usage = None
    if response is not None:
        choices = response.get("choices") or []
        content = (choices[0].get("message") or {}).get("content") if choices else None
        if isinstance(content, str) and content.strip():
            raw_text = content.strip()
            final_message = raw_text
            usage = response.get("usage")
        else:
            finish_reason = (choices[0].get("finish_reason") if choices else None) or "unknown"
            error_detail = f"empty message.content (finish_reason={finish_reason})"
    status = "ok" if raw_text else ("model_timeout" if termination == "timeout" else "model_error")
    output_truncated = False
    if len(raw_text.encode("utf-8")) > MAX_CANDIDATE_BYTES:
        raw_text = ""
        output_truncated = True
        status = "model_error"
        error_detail = "candidate exceeded MAX_CANDIDATE_BYTES"
    if raw_text:
        try:
            (workspace / "Candidate.lean").write_text(raw_text + "\n", encoding="utf-8")
        except OSError:
            pass
    logs_dir = generations_path.parent.resolve() / "logs"
    # Re-create defensively: the directories are created up front, but an external
    # move/remove mid-run should not lose the finished record.
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / f"{token}.response.json").write_text(
        json.dumps(
            {
                "prompt": prompt,
                "error": error_detail or None,
                "usage": usage,
                "response": response,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    record = {
        "run_id": run_id,
        "track": "direct_model",
        "item_index": item.index,
        "item_name": item.label,
        "item_repo": item.repo,
        "sample_id": sample_id,
        "model": config.model,
        "status": status,
        "exit_code": 0 if status == "ok" else 1,
        "termination_reason": termination,
        "error_detail": error_detail or None,
        "started_at": started_at,
        "finished_at": utc_now(),
        "wall_ms": wall_ms,
        "workspace": str(workspace),
        "events_path": str(logs_dir / f"{token}.response.json"),
        "compile_attempts": 0,
        "output_truncated": output_truncated,
        "raw_text": raw_text,
        "agent_final_message": final_message,
        "usage": usage,
    }
    async with write_lock:
        generations_path.parent.mkdir(parents=True, exist_ok=True)
        with generations_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


async def _run_one_direct_guarded(
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
    """One failed item must not abort the whole batch: record and continue."""
    try:
        await _run_one_direct(item, sample_id, run_id, config, generations_path, cache_home, elan_home, write_lock, semaphore)
    except Exception as exc:  # noqa: BLE001 - batch resilience for long unattended runs
        record = {
            "run_id": run_id,
            "track": "direct_model",
            "item_index": item.index,
            "item_name": item.label,
            "item_repo": item.repo,
            "sample_id": sample_id,
            "model": config.model,
            "status": "internal_error",
            "exit_code": 1,
            "termination_reason": None,
            "error_detail": f"{type(exc).__name__}: {exc}",
            "started_at": utc_now(),
            "finished_at": utc_now(),
            "wall_ms": 0,
            "workspace": "",
            "events_path": "",
            "compile_attempts": 0,
            "output_truncated": False,
            "raw_text": "",
            "agent_final_message": None,
            "usage": None,
        }
        async with write_lock:
            generations_path.parent.mkdir(parents=True, exist_ok=True)
            with generations_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")


async def run_direct(
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
            _run_one_direct_guarded(item, sample_id, run_id, config, generations_path, cache_home, elan_home, write_lock, semaphore)
            for item in items
            for sample_id in range(config.samples)
        )
    )
    return generations_path
