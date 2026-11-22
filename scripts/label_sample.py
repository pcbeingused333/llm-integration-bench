#!/usr/bin/env python3
"""Draw the hand-labelling samples and print them for labelling, without the classifier's answer.

Usage: label_sample.py <merge-log-data> <dev|test> [N]
The two samples are disjoint and drawn with fixed seeds. Rules are tuned on `dev` only; `test` is
labelled before the classifier's output on it is looked at, and scored once.
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import classify  # noqa: E402

root, which = sys.argv[1], sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else {"dev": 30, "test": 60}[which]
keys = sorted((p.parent.parent.name + "/" + p.parent.name, int(p.stem)) for p in Path(root, "fixes").glob("*/*/*.json"))
rng = random.Random(20261122)
rng.shuffle(keys)
chosen = keys[:30] if which == "dev" else keys[30:30 + n]
if which == "dev":
    chosen = chosen[:n]
for i, (repo, num) in enumerate(chosen, 1):
    rec = classify.load(root, repo, num)
    paths, lines = classify.changed_lines(rec)
    print(f"[{which}{i}] {repo}#{num}: {rec['title']}")
    print("  files:", ", ".join(paths[:4]) or "(only tests/docs)", f"(+{max(0, len(paths) - 4)})" if len(paths) > 4 else "")
    for ln in lines[:9]:
        print("   ", ln.strip()[:100])
