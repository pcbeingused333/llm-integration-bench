#!/usr/bin/env python3
"""Make a results file safe to publish: strip the account name and local paths.

Error text in the records contains absolute paths (the work directory, the toolchain caches,
Python tracebacks). On a personal machine those include the account name, and these results go
into a public repository. This rewrites them to placeholders and reports anything left.

Usage: sanitize_results.py <in.jsonl|in.json> <out> --workdir <the --workdir passed to run_pool>
"""
import argparse, json, os, re, sys

ap = argparse.ArgumentParser()
ap.add_argument("src"), ap.add_argument("dst")
ap.add_argument("--workdir", required=True)
a = ap.parse_args()

work = os.path.abspath(a.workdir)
home = os.path.expanduser("~")
user = os.path.basename(home.rstrip("/"))
rules = [
    (re.escape(work) + r"(?:/[^\s\"']*)?", "<workdir>"),
    (r"/mnt/[a-z]/Users/[^/\s\"']+", "/mnt/c/Users/<user>"),
    (r"/(?:home|Users)/[^/\s\"']+", "/home/<user>"),
    (r"/root\b", "/home/<user>"),
]

def clean(o):
    if isinstance(o, str):
        for pat, rep in rules:
            o = re.sub(pat, rep, o)
        return o.replace(user, "<user>") if len(user) > 3 else o
    if isinstance(o, list):
        return [clean(x) for x in o]
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    return o

text = open(a.src, encoding="utf-8").read()
if a.src.endswith(".jsonl"):
    rows = [json.loads(l) for l in text.splitlines() if l.strip()]
    out = [clean(r) for r in rows]
    open(a.dst, "w", encoding="utf-8").write("".join(json.dumps(r) + "\n" for r in out))
else:
    rows = json.loads(text)
    out = clean(rows)
    json.dump(out, open(a.dst, "w", encoding="utf-8"), indent=1)

blob = open(a.dst, encoding="utf-8").read()
left = [m for m in (user, home, work) if m and len(m) > 3 and m in blob]
print(f"{len(rows)} records written to {a.dst}")
if left:
    print("STILL PRESENT, do not publish:", left)
    sys.exit(1)
print("no account name or local path left")
