#!/usr/bin/env python3
"""Score each merged fix in merge-log-data for benchmark viability, from the diff alone.

A benchmark instance needs three things the diff can tell us about:
  1. a code change (something to repair) AND a test change (something to grade with);
  2. a diff that is not dominated by lockfiles, vendored trees or generated output,
     because those cannot be applied to a base checkout and re-run meaningfully;
  3. a test that can run offline. In this domain that is the binding constraint: a test
     that needs a live provider key is not gradeable in a sealed container.

Usage: score_fixes.py <path-to-merge-log-data> [out.json]
"""
from __future__ import annotations

import collections
import glob
import json
import os
import re
import sys

# Paths that cannot be replayed on a base checkout.
NOISE = re.compile(
    r"(^|/)(vendor|node_modules|dist|build|\.generated)/"
    r"|(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|uv\.lock"
    r"|go\.sum|Cargo\.lock|Gemfile\.lock|composer\.lock|packages\.lock\.json)$"
    r"|\.(snap|pb\.go|generated\.(ts|cs|go))$",
    re.I,
)
DOCS = re.compile(r"\.(md|mdx|rst|txt|adoc)$|^(docs|website)/", re.I)

# A test that reaches a real provider: the instance is not gradeable offline.
LIVE = re.compile(
    r"(OPENAI|ANTHROPIC|GEMINI|GOOGLE|GROQ|MISTRAL|COHERE|DEEPSEEK|XAI|TOGETHER|FIREWORKS"
    r"|AZURE_OPENAI|VERTEX|AWS_SECRET|AWS_ACCESS)_?[A-Z_]*(API_?KEY|TOKEN|CREDENTIAL)"
    r"|skip_?if[^\n]*api_?key|requires?_?api_?key|@pytest\.mark\.(llm|integration|e2e|live)"
    r"|testing\.Short\(\)|_INTEGRATION_TESTS|RUN_LIVE|live_?test",
    re.I,
)
# A test that fakes the provider: gradeable offline.
OFFLINE = re.compile(
    r"\bmock|\bMock\b|monkeypatch|unittest\.mock|respx|httpx_mock|responses\.|requests_mock"
    r"|vcr|cassette|betamax|nock\(|msw|gomock|httptest\.|NewServer\(|moq|WireMock|MockWebServer"
    r"|FakeHttp|stub|Stub|fixture|Substitute\.For|Mockito|webmock|\bdouble\b|sinon",
    re.I,
)


def added_lines(patch: str) -> str:
    return "\n".join(l[1:] for l in (patch or "").splitlines() if l.startswith("+"))


def main() -> int:
    root = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else None

    meta = {
        (p["repo"], p["number"]): p
        for p in json.load(open(os.path.join(root, "data/pull_requests.json")))
    }

    rows = []
    for fp in sorted(glob.glob(os.path.join(root, "fixes/*/*/*.json"))):
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        pr = meta.get((d.get("repo"), d.get("number")), {})
        files = d.get("files") or []
        test_names = set(d.get("test_files") or [])

        tests = [f for f in files if f.get("filename") in test_names]
        code = [f for f in files if f.get("filename") not in test_names]
        code_real = [f for f in code if not DOCS.search(f.get("filename", ""))]

        churn = lambda fs: sum(f.get("additions", 0) + f.get("deletions", 0) for f in fs)
        noisy = [f["filename"] for f in files if NOISE.search(f.get("filename", ""))]
        test_added = "\n".join(added_lines(f.get("patch", "")) for f in tests)

        live = bool(LIVE.search(test_added))
        offline = bool(OFFLINE.search(test_added))

        if not tests:
            verdict, why = "no", "no test in the diff"
        elif not code_real:
            verdict, why = "no", "test-only or docs-only change"
        elif noisy:
            verdict, why = "no", "lockfile, vendored or generated files in the diff"
        elif live:
            verdict, why = "no", "test needs a live provider credential"
        elif offline:
            verdict, why = "candidate", "test fakes the provider"
        else:
            verdict, why = "maybe", "no explicit mock; needs a run to tell"

        rows.append(
            dict(
                repo=d["repo"], number=d["number"], url=d.get("url"), title=d.get("title"),
                lang=pr.get("repo_language") or "?", stars=pr.get("repo_stars") or 0,
                category=pr.get("category") or "?", verdict=verdict, why=why,
                code_files=len(code_real), test_files=len(tests),
                code_churn=churn(code_real), test_churn=churn(tests),
            )
        )

    print(f"fixes with code recorded: {len(rows)}")
    tally = collections.Counter(r["verdict"] for r in rows)
    for v in ("candidate", "maybe", "no"):
        print(f"  {v:<10} {tally[v]:>5}  ({100 * tally[v] // max(1, len(rows))}%)")

    print("\n--- why not, for the rejected")
    for why, n in collections.Counter(r["why"] for r in rows if r["verdict"] == "no").most_common():
        print(f"  {n:>5}  {why}")

    print("\n--- by language (candidate / maybe / no, and repos holding candidates)")
    by = collections.defaultdict(list)
    for r in rows:
        by[r["lang"]].append(r)
    print(f"  {'language':<13}{'cand':>6}{'maybe':>7}{'no':>6}{'repos':>7}")
    for lang, rs in sorted(by.items(), key=lambda x: -len([r for r in x[1] if r["verdict"] == "candidate"])):
        c = [r for r in rs if r["verdict"] == "candidate"]
        m = [r for r in rs if r["verdict"] == "maybe"]
        n = [r for r in rs if r["verdict"] == "no"]
        if not (c or m):
            continue
        print(f"  {lang:<13}{len(c):>6}{len(m):>7}{len(n):>6}{len({r['repo'] for r in c}):>7}")

    usable = [r for r in rows if r["verdict"] in ("candidate", "maybe")]
    print(f"\n--- usable pool: {len(usable)} across {len({r['repo'] for r in usable})} repos")
    print("--- usable by category")
    for c, n in collections.Counter(r["category"] for r in usable).most_common():
        print(f"  {n:>5}  {c}")
    print(f"\n--- usable in repos >=10k stars: {len([r for r in usable if r['stars'] >= 10000])}")
    print("--- usable by code-diff size")
    for lo, hi, name in ((0, 20, "tiny <20"), (20, 60, "small 20-60"), (60, 150, "medium 60-150"), (150, 10**9, "large >150")):
        n = len([r for r in usable if lo <= r["code_churn"] < hi])
        print(f"  {n:>5}  {name}")

    if out_path:
        json.dump(rows, open(out_path, "w"), indent=1)
        print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
