#!/usr/bin/env python3
"""Build the bug taxonomy of the LLM integration layer from the merged-fix corpus.

Each category gets: how many merged fixes, how many distinct repositories (recurrence is the
interesting number, not the raw count: a bug found once is a bug, a bug found in thirty code
bases is a design trap), the languages it appears in, which provider the title names, and
whether llm-drift-lint already has a rule for it.

Usage: taxonomy.py <merge-log-data> <scored.json> <out.md>
"""
from __future__ import annotations

import collections
import json
import re
import sys

PROVIDERS = [
    ("Anthropic", r"anthropic|claude|bedrock.?converse"),
    ("OpenAI", r"\bopenai\b|gpt-|\bo[134]\b|chat.?completions|responses api"),
    ("Google", r"gemini|vertex|google.?gen|palm"),
    ("AWS Bedrock", r"bedrock"),
    ("Azure", r"azure"),
    ("Ollama / local", r"ollama|llama\.cpp|vllm|lmstudio"),
    ("Mistral", r"mistral"),
    ("Cohere", r"cohere"),
]

# Which recurring patterns llm-drift-lint already covers, from its rule table.
COVERED = {
    "Retired model defaults": "LDL007",
    "Token usage and cost": "LDL013, LDL015, LDL016",
    "Provider API compatibility": "LDL001, LDL002, LDL005, LDL008, LDL009, LDL012",
    "Streaming and tool calls": "LDL010, LDL011",
    "Errors, retries and limits": "LDL014, LDL017, LDL018",
    "Parsing and validation": "LDL003",
}


def main() -> int:
    root, scored_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    prs = json.load(open(f"{root}/data/pull_requests.json"))
    patterns = json.load(open(f"{root}/data/patterns.json"))
    scored = {(r["repo"], r["number"]): r for r in json.load(open(scored_path))}
    merged = [p for p in prs if p.get("state") == "merged"]

    def provider_of(p):
        blob = f"{p.get('title','')} {p.get('repo','')}".lower()
        hits = [name for name, rx in PROVIDERS if re.search(rx, blob)]
        return hits

    cats = collections.defaultdict(list)
    for p in merged:
        cats[p.get("category") or "?"].append(p)

    L = []
    w = L.append
    w("# The bug taxonomy of the LLM integration layer")
    w("")
    w(f"Measured over {len(merged):,} pull requests merged by maintainers across "
      f"{len({p['repo'] for p in merged}):,} repositories. Every row is a fix that an "
      "upstream maintainer accepted, so the sample is not what looked wrong to me, it is what "
      "the people who own the code agreed was wrong.")
    w("")
    w("Recurrence is the column that matters. A defect in one code base is a defect. The same "
      "defect in thirty code bases is a trap the ecosystem walks into, which means it is worth "
      "a linter rule, a benchmark instance or a paragraph of documentation somewhere upstream.")
    w("")
    w("| Category | Merged | Repos | Languages | Providers named | Benchmark-usable | Lint rules |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    for cat, ps in sorted(cats.items(), key=lambda x: -len(x[1])):
        if cat in ("?", "Documentation"):
            continue
        repos = len({p["repo"] for p in ps})
        langs = collections.Counter(p.get("repo_language") or "?" for p in ps)
        langtxt = ", ".join(f"{k} {v}" for k, v in langs.most_common(3))
        provs = collections.Counter(x for p in ps for x in provider_of(p))
        provtxt = ", ".join(f"{k} {v}" for k, v in provs.most_common(3)) or "none named"
        usable = len([p for p in ps
                      if scored.get((p["repo"], p["number"]), {}).get("verdict")
                      in ("candidate", "maybe")])
        w(f"| **{cat}** | {len(ps)} | {repos} | {langtxt} | {provtxt} | {usable} | "
          f"{COVERED.get(cat, '—')} |")
    w("")
    w("## The named patterns")
    w("")
    w("These are the specific shapes behind the categories above, each one a mistake made "
      "independently by teams who never read each other's code.")
    w("")
    w("| Pattern | Merged fixes | Repos | Rule |")
    w("| --- | --- | --- | --- |")
    pat_rule = {
        "Defaults pointing at retired models": "LDL007",
        "Cache read and write tokens miscounted": "LDL016",
        "Streamed parallel tool calls merged when the provider omits an index": "LDL010",
        "Reasoning / thinking tokens missing from usage": "LDL013",
        "Sampling parameters sent to Claude models that reject them": "LDL001, LDL008",
        "Anthropic cumulative message_delta usage": "LDL015",
        "Unknown or unmapped finish / stop reasons": "LDL014, LDL018",
        "Gemini responses with no content or blocked": "LDL018",
    }
    plist = patterns if isinstance(patterns, list) else patterns.get("patterns", [])
    for e in plist:
        w(f"| {e['pattern']} | {e['merged_fixes']} | {e['repos']} | "
          f"{pat_rule.get(e['pattern'], '— *(no rule yet)*')} |")
    w("")
    uncovered = [e for e in plist if e["pattern"] not in pat_rule]
    w(f"Patterns with no rule yet: {len(uncovered)}"
      + (": " + ", ".join(e["pattern"] for e in uncovered) if uncovered else ""))
    w("")
    w("## What the distribution says")
    w("")
    tot = sum(len(v) for k, v in cats.items() if k not in ("?", "Documentation"))
    integ = sum(len(cats[k]) for k in
                ("Streaming and tool calls", "Provider API compatibility",
                 "Token usage and cost", "Retired model defaults", "Errors, retries and limits")
                if k in cats)
    w(f"- {integ} of {tot} merged fixes ({100 * integ // tot}%) are in the provider-facing "
      "layer: streaming, API compatibility, usage accounting, model defaults and error "
      "handling. Only the rest is ordinary application logic.")
    langs = collections.Counter(p.get("repo_language") or "?" for p in merged)
    w(f"- The layer is not a Python problem. Python is {langs['Python']} of the merged fixes, "
      f"but Go is {langs['Go']}, TypeScript {langs['TypeScript']}, C# {langs['C#']} and Ruby "
      f"{langs['Ruby']}. Tooling that only reads Python covers less than a third of where these "
      "bugs actually live.")
    covered_cats = [c for c in cats if c in COVERED]
    w(f"- {len(covered_cats)} of the categories already have at least one llm-drift-lint rule; "
      "the gaps are concurrency and async, RAG and vector stores, and observability, none of "
      "which a static model-id check can reach.")
    open(out_path, "w").write("\n".join(L) + "\n")
    print(f"wrote {out_path} ({len(L)} lines)")
    print()
    print("\n".join(L[:30]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
