# The bug taxonomy of the LLM integration layer

Measured over 1,488 pull requests merged by maintainers across 369 repositories. Every row is a fix that an upstream maintainer accepted, so the sample is not what looked wrong to me, it is what the people who own the code agreed was wrong.

Recurrence is the column that matters. A defect in one code base is a defect. The same defect in thirty code bases is a trap the ecosystem walks into, which means it is worth a linter rule, a benchmark instance or a paragraph of documentation somewhere upstream.

| Category | Merged | Repos | Languages | Providers named | Benchmark-usable | Lint rules |
| --- | --- | --- | --- | --- | --- | --- |
| **Application logic** | 413 | 202 | Python 113, Go 92, TypeScript 78 | OpenAI 6, Google 4, Anthropic 4 | 359 | — |
| **Streaming and tool calls** | 252 | 84 | Go 70, Python 64, TypeScript 38 | OpenAI 56, Anthropic 43, Google 21 | 229 | LDL010, LDL011 |
| **Provider API compatibility** | 230 | 80 | Python 81, Go 60, TypeScript 29 | Anthropic 83, OpenAI 47, Google 42 | 191 | LDL001, LDL002, LDL005, LDL008, LDL009, LDL012 |
| **Token usage and cost** | 141 | 72 | Python 42, Go 40, C# 21 | Google 36, Anthropic 33, OpenAI 25 | 109 | LDL013, LDL015, LDL016 |
| **Retired model defaults** | 121 | 78 | Python 56, Go 20, TypeScript 17 | Anthropic 52, Google 34, OpenAI 32 | 68 | LDL007 |
| **Errors, retries and limits** | 116 | 80 | Python 42, Go 27, Rust 12 | OpenAI 10, Anthropic 7, Google 5 | 102 | LDL014, LDL017, LDL018 |
| **Parsing and validation** | 80 | 56 | Python 31, Go 19, TypeScript 9 | OpenAI 2, Ollama / local 1 | 75 | LDL003 |
| **Concurrency and async** | 46 | 31 | Python 28, TypeScript 4, Ruby 4 | Anthropic 4, OpenAI 2, Cohere 1 | 42 | — |
| **RAG and vector stores** | 45 | 20 | C# 20, Python 14, Ruby 4 | Cohere 4, OpenAI 3, Ollama / local 1 | 42 | — |
| **Observability and tracing** | 14 | 10 | Python 8, PHP 2, Kotlin 1 | OpenAI 3, Anthropic 2, AWS Bedrock 1 | 13 | — |
| **Security** | 13 | 13 | Go 4, TypeScript 2, Rust 2 | none named | 11 | — |

## The named patterns

These are the specific shapes behind the categories above, each one a mistake made independently by teams who never read each other's code.

| Pattern | Merged fixes | Repos | Rule |
| --- | --- | --- | --- |
| Defaults pointing at retired models | 96 | 61 | LDL007 |
| Unknown or unmapped finish / stop reasons | 73 | 29 | LDL014, LDL018 |
| Cache read and write tokens miscounted | 37 | 25 | LDL016 |
| Streamed parallel tool calls merged when the provider omits an index | 29 | 27 | LDL010 |
| Reasoning / thinking tokens missing from usage | 25 | 23 | LDL013 |
| Sampling parameters sent to Claude models that reject them | 24 | 17 | LDL001, LDL008 |
| Anthropic cumulative message_delta usage | 13 | 12 | LDL015 |
| Gemini responses with no content or blocked | 9 | 8 | LDL018 |
| Tool calls with empty or invalid JSON arguments | 5 | 5 | — *(no rule yet)* |

Patterns with no rule yet: 1: Tool calls with empty or invalid JSON arguments

## What the distribution says

- 860 of 1471 merged fixes (58%) are in the provider-facing layer: streaming, API compatibility, usage accounting, model defaults and error handling. Only the rest is ordinary application logic.
- The layer is not a Python problem. Python is 489 of the merged fixes, but Go is 339, TypeScript 211, C# 132 and Ruby 120. Tooling that only reads Python covers less than a third of where these bugs actually live.
- 6 of the categories already have at least one llm-drift-lint rule; the gaps are concurrency and async, RAG and vector stores, and observability, none of which a static model-id check can reach.
