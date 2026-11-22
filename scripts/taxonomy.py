#!/usr/bin/env python3
"""Build the bug taxonomy of the LLM integration layer from the merged-fix corpus.

Each fix is classified from what its diff changes (see classify.py), not from its title. Per
category the table gives how many fixes, how many distinct repositories (recurrence is the
interesting number: a bug found once is a bug, a bug found in thirty code bases is a design
trap), the languages, the providers the title names, how many of the fixes reproduced as
benchmark instances, and whether llm-drift-lint has a rule for it.

Usage: taxonomy.py <merge-log-data> <scored_snapshot.json> <pool_final.json> <out.md>
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import classify  # noqa: E402

PROVIDERS = [
    ("Anthropic", r"anthropic|claude"),
    ("OpenAI", r"\bopenai\b|gpt-|\bo[134]\b|chat.?completions|responses api"),
    ("Google", r"gemini|vertex|google.?gen"),
    ("AWS Bedrock", r"bedrock"),
    ("Azure", r"azure"),
    ("Ollama / local", r"ollama|llama\.cpp|vllm|lmstudio"),
    ("Mistral", r"mistral"),
    ("Cohere", r"cohere"),
]

COVERED = {
    "Retired model defaults": "LDL007",
    "Token usage and cost": "LDL013, LDL015, LDL016",
    "Provider API compatibility": "LDL001, LDL002, LDL005, LDL008, LDL009, LDL012",
    "Streaming and tool calls": "LDL010, LDL011",
    "Errors, retries and limits": "LDL014, LDL017, LDL018",
    "Parsing and validation": "LDL003",
}

PATTERN_RULE = {
    "Defaults pointing at retired models": "LDL007",
    "Cache read and write tokens miscounted": "LDL016",
    "Streamed parallel tool calls merged when the provider omits an index": "LDL010",
    "Reasoning / thinking tokens missing from usage": "LDL013",
    "Sampling parameters sent to Claude models that reject them": "LDL001, LDL008",
    "Anthropic cumulative message_delta usage": "LDL015",
    "Unknown or unmapped finish / stop reasons": "LDL014, LDL018",
    "Gemini responses with no content or blocked": "LDL018",
}


def main() -> int:
    root, snap_path, pool_path, out_path = sys.argv[1:5]
    snap = json.load(open(snap_path))
    outcome = {(r["repo"], r["number"]): r["outcome"] for r in json.load(open(pool_path))}
    cats = collections.defaultdict(list)
    for r in snap:
        cats[classify.classify(classify.load(root, r["repo"], r["number"]))[0]].append(r)
    total = len(snap)
    layer = [c for c in cats if c not in (classify.NOT_PROVIDER, "Documentation")]
    in_layer = sum(len(cats[c]) for c in layer)

    L: list[str] = []
    w = L.append
    w("# The bug taxonomy of the LLM integration layer")
    w("")
    w(f"{total:,} pull requests merged by upstream maintainers, in "
      f"{len({r['repo'] for r in snap}):,} repositories, each with code changes. Every one is a fix a "
      "maintainer accepted, so the sample is what the people who own the code agreed was wrong.")
    w("")
    w("Recurrence is the column that matters. A defect in one code base is a defect. The same defect "
      "in thirty code bases is a trap the ecosystem walks into, which makes it worth a lint rule, a "
      "benchmark instance or a paragraph of documentation.")
    w("")
    w("## How each fix was classified")
    w("")
    w("From the lines it adds and removes outside tests and docs: the vocabulary of each category "
      "is counted and the strongest wins. A fix whose title and changed lines name no provider, "
      "model, SDK or wire-format term is classified **Not provider-facing** instead of being forced "
      "into a bucket. The first version of this taxonomy took the first regular expression that "
      "matched the title and had a catch-all of 458; it also put fixes titled \"fail to parse\" under "
      "errors whether or not an LLM was anywhere in the diff.")
    w("")
    w("Measured on 60 fixes drawn at random and labelled by hand before the classifier saw them "
      "(rules were tuned on a separate 30; the 60 were scored once):")
    w("")
    w("| | Correct | 95% interval |")
    w("| --- | --- | --- |")
    w("| Exact category | 51 of 60 (85%) | 74% to 92% |")
    w("| Provider-facing or not | 55 of 60 (92%) | 82% to 96% |")
    w("")
    w("One labeller (me), so the labels carry my judgement and the borderline cases (a finish-reason "
      "fix inside a stream, a retry fix in a generic SDK) could go the other way. The sample is too "
      "small to say how accurate each category is on its own.")
    w("")
    w("## What the layer is")
    w("")
    w("| Category | Fixes | Repos | Languages | Providers named in the title | Reproduced, of those attempted | Lint rules |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    for cat, rs in sorted(((c, cats[c]) for c in layer), key=lambda x: -len(x[1])):
        repos = len({r["repo"] for r in rs})
        langs = collections.Counter(r.get("lang") or "?" for r in rs)
        provs = collections.Counter(
            n for r in rs for n, rx in PROVIDERS if re.search(rx, r["title"].lower()))
        attempted = [r for r in rs if (r["repo"], r["number"]) in outcome]
        repro = sum(outcome[(r["repo"], r["number"])] == "REPRODUCED" for r in attempted)
        repro_txt = f"{repro} of {len(attempted)}" if attempted else "not attempted"
        w(f"| **{cat}** | {len(rs)} | {repos} | "
          f"{', '.join(f'{k} {v}' for k, v in langs.most_common(3))} | "
          f"{', '.join(f'{k} {v}' for k, v in provs.most_common(3)) or 'none named'} | "
          f"{repro_txt} | {COVERED.get(cat, '-')} |")
    npf = cats[classify.NOT_PROVIDER]
    w("")
    w(f"{in_layer} of {total:,} fixes ({in_layer / total:.0%}) land in the categories above. "
      f"{len(npf)} ({len(npf) / total:.0%}) are **Not provider-facing**: they fix ordinary software in "
      f"repositories that happen to call or wrap an LLM, in {len({r['repo'] for r in npf})} repositories. "
      f"{len(cats['Documentation'])} change documentation only.")
    w("")
    old = {(p["repo"], p["number"]): p.get("category")
           for p in json.load(open(f"{root}/data/pull_requests.json"))}
    old_five = ("Streaming and tool calls", "Provider API compatibility", "Token usage and cost",
                "Retired model defaults", "Errors, retries and limits")
    old_in = [r for r in snap if old.get((r["repo"], r["number"])) in old_five]
    flagged = {(r["repo"], r["number"]) for r in npf}
    old_flagged = sum((r["repo"], r["number"]) in flagged for r in old_in)
    w("An earlier version of this page, and the audit proposal built on it, said 58% of the fixes were "
      "in the provider-facing layer. That counted the five categories assigned from the title. "
      f"Of the {len(old_in)} fixes in them, {old_flagged} ({old_flagged / len(old_in):.0%}) are not "
      "provider-facing when the diff is read, mostly from the errors category, whose title pattern "
      "matched \"error\", \"fail\" and \"raise\" with no LLM in the change. Read the "
      f"{in_layer / total:.0%} above instead.")
    w("")
    w("Two categories are probably under-counted. **Errors, retries and limits** and **Parsing and "
      "validation** are small here because a fix that names a provider is drawn to **Provider API "
      "compatibility**; of the three hand-labelled errors fixes in the held-out 60, one was classified "
      "correctly and two as not provider-facing. Their real size is likely larger, and the counts above "
      "should not be read as their size.")
    w("")
    w("## The named patterns")
    w("")
    w("Specific shapes behind the categories, found by matching titles rather than diffs, so these "
      "counts are looser than the table above. Each is a mistake made independently by teams who "
      "never read each other's code.")
    w("")
    w("| Pattern | Merged fixes | Repos | Rule |")
    w("| --- | --- | --- | --- |")
    patterns = json.load(open(f"{root}/data/patterns.json"))
    plist = patterns if isinstance(patterns, list) else patterns.get("patterns", [])
    for e in plist:
        w(f"| {e['pattern']} | {e['merged_fixes']} | {e['repos']} | "
          f"{PATTERN_RULE.get(e['pattern'], '- *(no rule yet)*')} |")
    w("")
    langs = collections.Counter(r.get("lang") or "?" for r in snap)
    w("## What the distribution says")
    w("")
    w(f"- The layer is not a Python problem. Of the {total:,} fixes, {langs['Python']} are in Python "
      f"repositories, {langs['Go']} in Go, {langs['TypeScript']} in TypeScript, {langs['C#']} in C# and "
      f"{langs['Ruby']} in Ruby. Tooling that only reads Python covers a third of where these bugs live.")
    w("- Provider API compatibility is the largest category by a margin: what a model accepts, what the "
      "response contains, and how the two drift apart between releases. It is also where the "
      "classifier is most likely to be reached for by a fix that belongs elsewhere.")
    w("- Retired model defaults is the one category that is a calendar, not a coding mistake: it recurs "
      "on the providers' schedule, which is why the retirement feed exists as a separate project.")
    gaps = [c for c in layer if c not in COVERED]
    w(f"- No lint rule covers: {', '.join(gaps)}. A static model-id check cannot reach them.")
    open(out_path, "w").write("\n".join(L) + "\n")
    print(f"wrote {out_path} ({len(L)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
