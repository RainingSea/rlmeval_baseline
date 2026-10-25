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
        try:
            server, ctx_out = self.run_context(item.project_dir, item.context, timeout=timeout_context)
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

    def run_context(self, project_dir: str, context: str, *, timeout: int) -> tuple[AutoLeanServer, object]:
        server = self.server(project_dir)
        try:
            return server, server.run(Command(cmd=context), add_to_session_cache=True, timeout=timeout)
        except Exception:  # noqa: BLE001
            try:
                server.kill()
            finally:
                self._servers.pop(project_dir, None)
            server = self.server(project_dir)
            return server, server.run(Command(cmd=context), add_to_session_cache=False, timeout=timeout)

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
