#!/usr/bin/env python3
"""Score the classifier against a hand-labelled file. Usage: score_labels.py <merge-log-data> <labels.json>"""
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import classify  # noqa: E402

root, labels = sys.argv[1], json.load(open(sys.argv[2]))
ok = 0
confusion = collections.Counter()
for o in labels:
    got, _ = classify.classify(classify.load(root, o["repo"], o["number"]))
    ok += got == o["label"]
    if got != o["label"]:
        confusion[(o["label"], got)] += 1
        print(f"  {o['id']}: label={o['label']!r} got={got!r}  {o['title'][:70]}")
print(f"accuracy {ok}/{len(labels)} = {ok / len(labels):.0%}")
