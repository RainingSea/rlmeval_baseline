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
