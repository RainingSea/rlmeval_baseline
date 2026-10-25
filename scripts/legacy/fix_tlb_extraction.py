#!/usr/bin/env python3
import json
import os
from pathlib import Path

BASE = Path('/data/projects/math-harness-eval')
ROOT = BASE / 'RLMEval'
os.environ.setdefault('HOME', str(BASE / 'rlm-env/home'))
os.environ.setdefault('TMPDIR', str(BASE / 'rlm-env/tmp'))

import jsonlines
from rlm_eval.data_processing.blueprint_extractor import extract_blueprint_info
from rlm_eval.data_processing.blueprint_lean_linking import merge_blueprint_lean_dep_graphs

out = (ROOT / 'traced_repos' / 'tlb-src_0f09ff100a06a5e4542181514bfff74213ae126b').resolve()
bp = extract_blueprint_info(str(out / 'tlb-src' / 'blueprint'))
with jsonlines.open(out / 'blueprint.jsonl', 'w') as w:
    w.write_all(bp)
os.chdir(ROOT)
merged = merge_blueprint_lean_dep_graphs(bp, list(jsonlines.open(out / 'lean_declarations.jsonl')))
with jsonlines.open(out / 'blueprint_to_lean.jsonl', 'w') as w:
    w.write_all(merged)
(ROOT / 'traced_repos' / 'success.json').write_text(json.dumps([['PFR', 'Success'], ['TLB', 'Success']]))
print('TLB nodes:', len(bp), 'theorem-linked:', len(merged))
