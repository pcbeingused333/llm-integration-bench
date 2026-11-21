#!/usr/bin/env python3
"""Summarise a results .jsonl while a run is in progress: counts per outcome, per language, and
the reproduction rate so far. Safe to run at any time; it only reads."""
import collections, json, sys

rows = {}
for line in open(sys.argv[1]):
    try:
        r = json.loads(line)
    except ValueError:
        continue
    rows[(r["repo"], r["number"])] = r
rows = list(rows.values())
n = len(rows)
if not n:
    print("no results yet")
    raise SystemExit
print(f"{n} instances finished")
for k, v in collections.Counter(r["outcome"] for r in rows).most_common():
    print(f"  {v:>5}  {100*v/n:>3.0f}%  {k}")
print("by language (reproduced / finished):")
for lang in sorted({r["lang"] for r in rows}):
    ls = [r for r in rows if r["lang"] == lang]
    k = sum(r["outcome"] == "REPRODUCED" for r in ls)
    print(f"  {lang:<11}{k:>5} / {len(ls):<5} {100*k/len(ls):.0f}%")
secs = sum(r.get("seconds", 0) for r in rows)
print(f"mean {secs/n:.0f}s per instance")
