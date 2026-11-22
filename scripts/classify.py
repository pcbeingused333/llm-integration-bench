#!/usr/bin/env python3
"""Classify a merged fix by what its diff changes, not by the words in its title.

The first taxonomy took the first regular expression that matched the title. That puts a fix
titled "fail to parse" under errors and a fix titled "handle chunk size" under streaming, and it
leaves every title that names nothing in a catch-all of 458. This classifier reads the lines the
fix added and removed outside the tests, counts the signals of each category, and takes the
strongest. A fix that touches no provider-facing code is reported as such rather than forced into
a bucket, because most of the catch-all was never in the LLM layer to begin with.

Usage as a library: classify(record) -> (category, scores). `record` is a fixes/<owner>/<repo>/<n>.json
object. Usage as a script: classify.py <merge-log-data> prints the distribution.
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

NOT_PROVIDER = "Not provider-facing"

DOC_EXT = (".md", ".mdx", ".rst", ".txt", ".adoc", ".ipynb")

# A line that mentions a provider, its SDK or the vocabulary of its wire format. A fix with none
# of these in its title or its changed lines does not touch the provider-facing layer.
SURFACE = re.compile(
    r"anthropic|openai|claude|gemini|vertex|bedrock|mistral|cohere|deepseek|ollama|groq|llama|"
    r"gpt-?\d|\bo[134]-|litellm|langchain|llm|chat[._]?completion|messages\.create|generate_?content|"
    r"finish_?reason|stop_?reason|tool_?calls?|tool_?use|tool_?choice|function_?call|"
    r"(prompt|completion|input|output)_tokens|max_(completion_)?tokens|temperature|top_p|"
    r"embeddings?[_.\[(]|Embedding[A-Z(]|vector[_ ]?(store|db|database)|pgvector|qdrant|pinecone|faiss|chroma|milvus|"
    r"weaviate|lancedb|rerank|system_?prompt|\bprompts?\b|\bmodels?\b.{0,20}(name|id)",
    re.I)

# (category, [(regex, weight)]). Weights are per match in the changed code lines; a hit in the
# title counts three times. The order is only the tie-break.
SIGNALS = [
    ("Retired model defaults", [
        (r"\b(gpt-[345][\w.\-]*|claude-[\w.\-]+|gemini-[\w.\-]+|o[134](-mini|-pro)?\b|text-(davinci|embedding)[\w\-]*)", 1.5),
        (r"retir|deprecat|shut ?down|sunset|end[- ]of[- ]life", 2),
        (r"default[_ ]?model|DEFAULT_MODEL|model\s*[:=]\s*[\"']", 1.5),
    ]),
    ("Streaming and tool calls", [
        (r"stream|\bdeltas?\b|content_block|message_delta|\bsse\b|event-stream", 2),
        (r"tool_?calls?|tool_?use|tool_?choice|function_?call|tool_?result|tool_call_id", 2),
        (r"\bchunks?\b|\bindex\b", 0.7),
    ]),
    ("Token usage and cost", [
        (r"(prompt|completion|input|output|total|cached|reasoning)_?tokens|usage|cache_?(read|write|creation)", 2),
        (r"token_?count|thoughts?_?tokens|\btokens\b", 1.5),
        (r"\bcost|price|pricing|billing", 1.5),
    ]),
    ("Provider API compatibility", [
        (r"temperature|top_[pk]|max_(completion_)?tokens|budget_tokens|reasoning_?effort|thinking|response_format", 2),
        (r"finish_?reason|stop_?reason|refusal|stop_sequences?|\bcontent\[0\]|\.content\b|role.{0,12}(system|developer)", 1.5),
        (r"anthropic|openai|gemini|bedrock|vertex|mistral|cohere|deepseek|ollama|groq", 1),
    ]),
    ("Errors, retries and limits", [
        (r"retry|retries|backoff|rate[_ -]?limit|\b429\b|\b5\d\d\b|timeout|overloaded|context[_ ]length|APIError|APIStatusError", 2),
        (r"status_?code|errored|\berrors?\b|\bfailed\b", 1),
    ]),
    ("Parsing and validation", [
        (r"json\.loads|JSON\.parse|json\.Unmarshal|unmarshal|model_validate|pydantic|jsonschema|schema|"
         r"validat|parse|regex|re\.(sub|match|search)|strip\(|encod|decod|utf", 1.2),
    ]),
    ("RAG and vector stores", [
        (r"vector|embedding|retriev|rerank|qdrant|pinecone|faiss|chroma|milvus|weaviate|lancedb|pgvector|"
         r"chunker|chunking|document[_ ](store|loader)|ingest", 2),
    ]),
    ("Concurrency and async", [
        (r"\basync\b|\bawait\b|asyncio|event[_ ]loop|goroutine|sync\.|mutex|\block\b|thread|race|deadlock|"
         r"Promise\.all|concurren|semaphore", 1.6),
    ]),
    ("Observability and tracing", [
        (r"\bspans?\b|tracer|tracing|opentelemetry|otel|gen_ai\.|telemetry|metrics?\b|instrument", 2),
    ]),
    ("Security", [
        (r"secret|credential|password|\btoken\b.{0,10}(leak|log|expos)|ssrf|xss|sanitiz|plaintext|authoriz|"
         r"\bauth\b|permission|redact|mask", 1.6),
    ]),
]

MIN_SCORE = 3.0


def changed_lines(record: dict) -> tuple[list[str], list[str]]:
    """Added and removed lines of the files that are neither tests nor documentation."""
    tests = set(record.get("test_files") or [])
    lines: list[str] = []
    paths: list[str] = []
    for f in record.get("files", []):
        name = f["filename"]
        if name in tests or name.lower().endswith(DOC_EXT):
            continue
        paths.append(name)
        for ln in (f.get("patch") or "").splitlines():
            if ln[:1] in "+-" and not ln.startswith(("+++", "---")):
                lines.append(ln[1:])
    return paths, lines


def classify(record: dict) -> tuple[str, dict[str, float]]:
    paths, lines = changed_lines(record)
    if not paths:
        return "Documentation", {}
    title = record.get("title", "")
    body = "\n".join(lines)
    if not SURFACE.search(title) and not SURFACE.search(body):
        return NOT_PROVIDER, {}
    scores: dict[str, float] = {}
    for cat, rules in SIGNALS:
        s = 0.0
        for rx, w in rules:
            pat = re.compile(rx, re.I)
            s += w * (len(pat.findall(body)) ** 0.5 + 3 * len(pat.findall(title)))
        scores[cat] = round(s, 2)
    best = max(scores.items(), key=lambda kv: kv[1])
    if best[1] < MIN_SCORE:
        return NOT_PROVIDER, scores
    return best[0], scores


def load(root: str, repo: str, number: int) -> dict | None:
    p = Path(root) / "fixes" / repo / f"{number}.json"
    return json.loads(p.read_text()) if p.exists() else None


def main() -> int:
    root = sys.argv[1]
    counts = collections.Counter()
    n = 0
    for p in Path(root, "fixes").glob("*/*/*.json"):
        rec = json.loads(p.read_text())
        counts[classify(rec)[0]] += 1
        n += 1
    print(n)
    for k, v in counts.most_common():
        print(f"{v:5d}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
