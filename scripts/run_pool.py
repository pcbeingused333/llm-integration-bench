#!/usr/bin/env python3
"""Run the reproduction harness over a pool of instances: parallel, resumable, disk-aware.

Why each of those matters here:
  - resumable: a run over hundreds of instances takes hours and the machine is ephemeral.
    Every finished instance is appended to results.jsonl at once, and a restart skips any
    instance that already has a terminal outcome, so an interruption costs one instance.
  - one cache per toolchain, shared by all workers: dependency downloads dominate the cost and
    would otherwise be repeated per instance. (Earlier runs each created their own cache and
    left ~21 GB of duplicates on a disk with 25 GB free.)
  - disk-aware: before an instance starts, if free space is below a floor the shared caches are
    cleared. That costs re-downloads, which is better than a run that dies at 99%.

Usage:
  run_pool.py <merge-log-data> <scored.json> <workdir> <results.jsonl> [options]
    --langs Go,Python,TypeScript   languages with a runner (default)
    --per-lang N                   random sample of N per language (default: all)
    --per-repo K                   at most K instances from one repository (default: no cap)
    --verdicts candidate,maybe     scorer verdicts to include (default both)
    --seed S                       sampling seed (default 7)
    --workers W                    parallel instances (default 3)
    --min-free-gb G                clear caches when free disk falls under G (default 6)
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import importlib.util
import json
import os
import platform
import random
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TERMINAL = {"REPRODUCED", "TEST_PASSES_AT_BASE", "STILL_FAILS_AFTER_FIX", "RUNNER_ERROR",
            "NO_FIX_COMMIT", "SPLIT_FAIL", "APPLY_FAIL", "SETUP_FAIL", "NO_RUNNER", "TIMEOUT",
            "ERROR"}


def load_harness():
    spec = importlib.util.spec_from_file_location("reproduce", os.path.join(HERE, "reproduce.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def toolchain() -> dict:
    """The tool versions in effect, saved beside the results: outcomes depend on them (a newer
    Node or uv changes what installs and runs), so a result is only interpretable with them."""
    out = {}
    for name, cmd in (("go", ["go", "version"]), ("uv", ["uv", "--version"]),
                      ("node", ["node", "--version"]), ("pnpm", ["pnpm", "--version"]),
                      ("python", ["python3", "--version"]), ("gcc", ["gcc", "--version"])):
        try:
            out[name] = subprocess.run(cmd, capture_output=True, text=True,
                                       timeout=20).stdout.splitlines()[0]
        except Exception:
            out[name] = None
    out["os"] = platform.platform()
    out["cpus"] = os.cpu_count()
    return out


def free_gb(path: str) -> float:
    return shutil.disk_usage(path).free / 1e9


def work(args):
    root, inst, workdir, caches = args
    rep = load_harness()
    inst_dir = os.path.join(workdir, f"w{os.getpid()}")
    os.makedirs(inst_dir, exist_ok=True)
    return rep.one(inst, root, inst_dir, caches)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root"), ap.add_argument("scored"), ap.add_argument("workdir")
    ap.add_argument("results")
    ap.add_argument("--langs", default="Go,Python,TypeScript")
    ap.add_argument("--per-lang", type=int, default=0)
    ap.add_argument("--per-repo", type=int, default=0)
    ap.add_argument("--verdicts", default="candidate,maybe")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--min-free-gb", type=float, default=10.0)
    ap.add_argument("--retry-from", help="a results .jsonl: rerun only the instances in it whose "
                    "outcome is one of --retry-outcomes, ignoring sampling")
    ap.add_argument("--retry-outcomes", default="SETUP_FAIL,RUNNER_ERROR,NO_RUNNER,ERROR")
    a = ap.parse_args()

    langs = set(a.langs.split(","))
    verdicts = set(a.verdicts.split(","))
    rows = [r for r in json.load(open(a.scored))
            if r["verdict"] in verdicts and r["lang"] in langs]

    done = set()
    if os.path.exists(a.results):
        for line in open(a.results):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("outcome") in TERMINAL:
                done.add((r["repo"], r["number"]))

    if a.retry_from:
        wanted = set()
        latest = {}
        for line in open(a.retry_from):
            r = json.loads(line)
            latest[(r["repo"], r["number"])] = r
        for k, r in latest.items():
            if r["outcome"] in set(a.retry_outcomes.split(",")):
                wanted.add(k)
        chosen = [r for r in json.load(open(a.scored)) if (r["repo"], r["number"]) in wanted]
        done = set()
        langs = {r["lang"] for r in chosen}
    rnd = random.Random(a.seed)
    if not a.retry_from:
        chosen = []
    for lang in (sorted(langs) if not a.retry_from else []):
        pool = [r for r in rows if r["lang"] == lang]
        rnd.shuffle(pool)
        per_repo = collections.Counter()
        picked = []
        for r in pool:
            if a.per_repo and per_repo[r["repo"]] >= a.per_repo:
                continue
            per_repo[r["repo"]] += 1
            picked.append(r)
            if a.per_lang and len(picked) >= a.per_lang:
                break
        chosen += picked
    todo = [r for r in chosen if (r["repo"], r["number"]) not in done]

    print(f"selected {len(chosen)} instances ({len(done)} already have a terminal outcome); "
          f"{len(todo)} to run with {a.workers} workers", flush=True)
    for lang in sorted(langs):
        print(f"   {lang:<11} {len([r for r in chosen if r['lang'] == lang]):>4} selected, "
              f"{len({r['repo'] for r in chosen if r['lang'] == lang}):>3} repos", flush=True)
    if not todo:
        return 0

    os.makedirs(a.workdir, exist_ok=True)
    with open(a.results + ".toolchain.json", "w") as f:
        json.dump(dict(started=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       workers=a.workers, **toolchain()), f, indent=1)
    caches = {}
    for lang, sub in (("Go", "gomod"), ("Python", "uv"), ("TypeScript", "npm"),
                      ("JavaScript", "npm")):
        caches[lang] = os.path.join(os.path.abspath(a.workdir), "_cache", sub)
        os.makedirs(caches[lang], exist_ok=True)
    cache_root = os.path.join(os.path.abspath(a.workdir), "_cache")

    t0, n_done, tally = time.time(), 0, collections.Counter()
    with cf.ProcessPoolExecutor(max_workers=a.workers) as pool, open(a.results, "a") as out:
        pending, queue = set(), list(todo)

        def submit_more():
            while queue and len(pending) < a.workers:
                if free_gb(a.workdir) < a.min_free_gb:
                    if pending:
                        return
                    shutil.rmtree(cache_root, ignore_errors=True)
                    shutil.rmtree(os.path.expanduser("~/.cache/go-build"), ignore_errors=True)
                    for p in caches.values():
                        os.makedirs(p, exist_ok=True)
                    print(f"   [disk] under {a.min_free_gb} GB free, caches cleared", flush=True)
                inst = queue.pop(0)
                pending.add(pool.submit(work, (a.root, inst, a.workdir, caches)))

        submit_more()
        while pending:
            finished, _ = cf.wait(pending, return_when=cf.FIRST_COMPLETED)
            for fut in finished:
                pending.discard(fut)
                try:
                    rec = fut.result()
                except Exception as exc:
                    rec = {"repo": "?", "number": 0, "outcome": "ERROR",
                           "detail": f"{type(exc).__name__}: {exc}"}
                out.write(json.dumps(rec) + "\n")
                out.flush()
                n_done += 1
                tally[rec["outcome"]] += 1
                rate = (time.time() - t0) / n_done
                eta = rate * (len(todo) - n_done) / 3600
                print(f"[{n_done}/{len(todo)}] {rec.get('lang', ''):<10} {rec['outcome']:<22} "
                      f"{rec['repo']}#{rec['number']}  (eta {eta:.1f}h, "
                      f"{free_gb(a.workdir):.0f} GB free)", flush=True)
            submit_more()

    print("\n=== outcomes this run")
    for k, n in tally.most_common():
        print(f"  {n:>4}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
