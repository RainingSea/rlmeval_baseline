#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def parse_excluded_indices(spec: str) -> set[int]:
    if not spec.strip():
        return set()
    return {int(token.strip()) for token in spec.split(",") if token.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Select a reproducible benchmark subset.")
    parser.add_argument("--dataset", default="data/rlm25_pfr_tlb.jsonl")
    parser.add_argument("--project", choices=["PFR", "TLB", "all"], default="all")
    parser.add_argument("--count", type=int, default=0, help="0 selects every matching item")
    parser.add_argument("--seed", type=int, default=20261017)
    parser.add_argument("--exclude", default="", help="Comma-separated item indices")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = [json.loads(line) for line in dataset_path.read_text().splitlines() if line.strip()]
    excluded = parse_excluded_indices(args.exclude)
    candidates = [
        row
        for row in rows
        if (args.project == "all" or row["project_name"] == args.project)
        and int(row["index"]) not in excluded
    ]
    if not candidates:
        raise SystemExit("No benchmark items match the requested filters")
    if args.count < 0:
        raise SystemExit("--count must be non-negative")
    if args.count > len(candidates):
        raise SystemExit(f"Requested {args.count} items, but only {len(candidates)} are available")

    if args.count == 0:
        selected = candidates
    else:
        selected = random.Random(args.seed).sample(candidates, args.count)
    selected.sort(key=lambda row: int(row["index"]))

    manifest = [
        {
            "index": int(row["index"]),
            "name": row["name"],
            "project_name": row["project_name"],
            "file": row["file"],
        }
        for row in selected
    ]
    indices = ",".join(str(row["index"]) for row in manifest)

    (output_dir / "selection.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    (output_dir / "indices.txt").write_text(indices + "\n")
    with (output_dir / "selection.tsv").open("w", encoding="utf-8") as handle:
        handle.write("index\tname\tproject\tfile\n")
        for row in manifest:
            handle.write(
                f'{row["index"]}\t{row["name"]}\t{row["project_name"]}\t{row["file"]}\n'
            )

    print(f"selected={len(manifest)} project={args.project} seed={args.seed}")
    print(f"indices={indices}")
    print(f"manifest={output_dir / 'selection.tsv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
