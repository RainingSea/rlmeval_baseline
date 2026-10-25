#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_dataset(path: Path) -> dict[int, dict[str, Any]]:
    return {
        int(row["index"]): row
        for row in load_jsonl(path)
    }


def generation_error_reason(row: dict[str, Any]) -> str:
    if row.get("termination_reason"):
        return str(row["termination_reason"])

    events_path = Path(row.get("events_path", ""))
    if events_path.is_file():
        for event in reversed(load_jsonl(events_path)):
            if event.get("type") != "turn.failed":
                continue
            error = event.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error)
            if error:
                return str(error)

    return f'status={row.get("status", "missing")} exit_code={row.get("exit_code")}'


def markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize a Codex harness experiment.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifacts-dir", default="artifacts")
    parser.add_argument("--dataset", default="data/rlm25_pfr_tlb.jsonl")
    parser.add_argument("--output-dir")
    parser.add_argument("--expected-samples", type=int, default=0)
    args = parser.parse_args()

    run_dir = Path(args.artifacts_dir) / args.run_id
    output_dir = Path(args.output_dir) if args.output_dir else Path("run-logs") / args.run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    generations = load_jsonl(run_dir / "generations.jsonl")
    scores = load_jsonl(run_dir / "scores.jsonl")
    dataset = load_dataset(Path(args.dataset))

    generations_by_item: dict[int, list[dict[str, Any]]] = defaultdict(list)
    scores_by_item: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in generations:
        generations_by_item[int(row["item_index"])].append(row)
    for row in scores:
        scores_by_item[int(row["item_index"])].append(row)

    item_indices = sorted(set(generations_by_item) | set(scores_by_item))
    item_summaries: list[dict[str, Any]] = []
    for item_index in item_indices:
        item_generations = generations_by_item[item_index]
        item_scores = scores_by_item[item_index]
        dataset_row = dataset.get(item_index, {})
        passed_samples = sum(
            row.get("proof_ok") is True
            or row.get("beq_plus_ok") is True
            or row.get("score_status") in {"passed", "certified"}
            for row in item_scores
        )
        observed_samples = max(len(item_generations), len(item_scores))
        expected_samples = args.expected_samples or observed_samples
        item_summaries.append(
            {
                "index": item_index,
                "name": (
                    item_generations[0].get("item_name")
                    if item_generations
                    else dataset_row.get("name", "unknown")
                ),
                "project": (
                    item_generations[0].get("item_repo")
                    if item_generations
                    else dataset_row.get("project_name", "unknown")
                ),
                "expected_samples": expected_samples,
                "generated_samples": len(item_generations),
                "generation_statuses": dict(
                    Counter(row.get("status", "missing") for row in item_generations)
                ),
                "scored_samples": len(item_scores),
                "score_statuses": dict(
                    Counter(row.get("score_status", "missing") for row in item_scores)
                ),
                "passed_samples": passed_samples,
                "pass_at_k": passed_samples > 0,
            }
        )

    passed_samples_total = sum(item["passed_samples"] for item in item_summaries)
    solved_items = sum(item["pass_at_k"] for item in item_summaries)
    scored_samples_total = len(scores)
    generation_error_details = [
        {
            "index": int(row["item_index"]),
            "name": row.get("item_name", "unknown"),
            "project": row.get("item_repo", "unknown"),
            "generation_status": row.get("status", "missing"),
            "reason": generation_error_reason(row),
            "compile_attempts": row.get("compile_attempts", 0),
            "source_run_id": row.get("source_run_id", row.get("run_id", args.run_id)),
            "events_path": row.get("events_path", ""),
        }
        for row in generations
        if row.get("status") not in {"ok", "completed"}
    ]
    summary = {
        "run_id": args.run_id,
        "artifacts_dir": str(run_dir),
        "items": len(item_summaries),
        "generated_samples": len(generations),
        "scored_samples": scored_samples_total,
        "passed_samples": passed_samples_total,
        "sample_pass_rate": (
            passed_samples_total / scored_samples_total if scored_samples_total else 0.0
        ),
        "solved_items": solved_items,
        "observed_pass_at_k_rate": solved_items / len(item_summaries) if item_summaries else 0.0,
        "generation_statuses": dict(Counter(row.get("status", "missing") for row in generations)),
        "score_statuses": dict(Counter(row.get("score_status", "missing") for row in scores)),
        "generation_error_details": generation_error_details,
        "item_results": item_summaries,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    )

    expected_values = {item["expected_samples"] for item in item_summaries}
    pass_label = (
        f"Pass@{next(iter(expected_values))}"
        if len(expected_values) == 1 and expected_values
        else "Observed Pass@k"
    )
    lines = [
        f"# {args.run_id}",
        "",
        f"- Items: {len(item_summaries)}",
        f"- Generated samples: {len(generations)}",
        f"- Scored samples: {scored_samples_total}",
        f"- Passed samples: {passed_samples_total}",
        f"- Sample pass rate: {summary['sample_pass_rate']:.2%}",
        f"- Solved items ({pass_label}): {solved_items}/{len(item_summaries)}",
        f"- {pass_label} rate: {summary['observed_pass_at_k_rate']:.2%}",
        f"- Generation statuses: `{summary['generation_statuses']}`",
        f"- Score statuses: `{summary['score_statuses']}`",
        "",
    ]
    if generation_error_details:
        lines.extend(
            [
                "## Generation Errors",
                "",
                "| Index | Project | Item | Generation status | Attempts | Reason | Source run | Events |",
                "|---:|---|---|---|---:|---|---|---|",
            ]
        )
        for detail in generation_error_details:
            lines.append(
                f'| {detail["index"]} | {markdown_cell(detail["project"])} | '
                f'{markdown_cell(detail["name"])} | '
                f'{markdown_cell(detail["generation_status"])} | '
                f'{detail["compile_attempts"]} | {markdown_cell(detail["reason"])} | '
                f'{markdown_cell(detail["source_run_id"])} | '
                f'`{markdown_cell(detail["events_path"])}` |'
            )
        lines.extend(["", "## Item Results", ""])
    lines.extend(
        [
            f"| Index | Project | Item | Generated | Scored | Passed | {pass_label} | Score statuses |",
            "|---:|---|---|---:|---:|---:|:---:|---|",
        ]
    )
    for item in item_summaries:
        statuses = ", ".join(
            f"{name}={count}" for name, count in sorted(item["score_statuses"].items())
        ) or "none"
        lines.append(
            f'| {item["index"]} | {item["project"]} | {item["name"]} | '
            f'{item["generated_samples"]}/{item["expected_samples"]} | '
            f'{item["scored_samples"]}/{item["expected_samples"]} | '
            f'{item["passed_samples"]} | {"yes" if item["pass_at_k"] else "no"} | '
            f"{statuses} |"
        )
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n")

    print(f"summary_json={output_dir / 'summary.json'}")
    print(f"summary_md={output_dir / 'summary.md'}")
    print(
        f"passed_samples={passed_samples_total}/{scored_samples_total} "
        f"solved_items={solved_items}/{len(item_summaries)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
