# The bug taxonomy of the LLM integration layer

1,605 pull requests merged by upstream maintainers, in 391 repositories, each with code changes. Every one is a fix a maintainer accepted, so the sample is what the people who own the code agreed was wrong.

Recurrence is the column that matters. A defect in one code base is a defect. The same defect in thirty code bases is a trap the ecosystem walks into, which makes it worth a lint rule, a benchmark instance or a paragraph of documentation.

## How each fix was classified

From the lines it adds and removes outside tests and docs: the vocabulary of each category is counted and the strongest wins. A fix whose title and changed lines name no provider, model, SDK or wire-format term is classified **Not provider-facing** instead of being forced into a bucket. The first version of this taxonomy took the first regular expression that matched the title and had a catch-all of 458; it also put fixes titled "fail to parse" under errors whether or not an LLM was anywhere in the diff.

Measured on 60 fixes drawn at random and labelled by hand before the classifier saw them (rules were tuned on a separate 30; the 60 were scored once):

| | Correct | 95% interval |
| --- | --- | --- |
| Exact category | 51 of 60 (85%) | 74% to 92% |
| Provider-facing or not | 55 of 60 (92%) | 82% to 96% |

One labeller (me), so the labels carry my judgement and the borderline cases (a finish-reason fix inside a stream, a retry fix in a generic SDK) could go the other way. The sample is too small to say how accurate each category is on its own.

## What the layer is

| Category | Fixes | Repos | Languages | Providers named in the title | Reproduced, of those attempted | Lint rules |
| --- | --- | --- | --- | --- | --- | --- |
| **Provider API compatibility** | 301 | 88 | Python 102, Go 89, TypeScript 31 | Anthropic 106, Google 54, OpenAI 50 | 145 of 197 | LDL001, LDL002, LDL005, LDL008, LDL009, LDL012 |
| **Streaming and tool calls** | 174 | 68 | Python 48, Go 40, TypeScript 28 | OpenAI 46, Anthropic 27, Ollama / local 16 | 89 of 114 | LDL010, LDL011 |
| **Retired model defaults** | 130 | 85 | Python 69, Go 21, TypeScript 17 | Anthropic 57, OpenAI 33, Google 33 | 34 of 58 | LDL007 |
| **Token usage and cost** | 115 | 57 | Python 40, Go 26, TypeScript 20 | Anthropic 33, Google 32, OpenAI 18 | 54 of 68 | LDL013, LDL015, LDL016 |
| **RAG and vector stores** | 54 | 20 | C# 21, Python 15, Ruby 6 | Cohere 7, OpenAI 3, AWS Bedrock 3 | 11 of 19 | - |
| **Errors, retries and limits** | 27 | 20 | Python 12, Go 5, TypeScript 3 | OpenAI 4, Anthropic 3, Google 3 | 14 of 19 | LDL014, LDL017, LDL018 |
| **Parsing and validation** | 10 | 9 | Python 5, C# 3, Go 1 | OpenAI 1, Cohere 1, Ollama / local 1 | 3 of 5 | LDL003 |
| **Concurrency and async** | 6 | 6 | Python 3, TypeScript 1, C# 1 | OpenAI 1 | 2 of 4 | - |
| **Security** | 6 | 5 | Python 3, Go 2, C# 1 | AWS Bedrock 2, OpenAI 1, Anthropic 1 | 3 of 4 | - |
| **Observability and tracing** | 5 | 5 | Python 4, TypeScript 1 | Google 1, OpenAI 1, Anthropic 1 | 2 of 4 | - |

828 of 1,605 fixes (52%) land in the categories above. 746 (46%) are **Not provider-facing**: they fix ordinary software in repositories that happen to call or wrap an LLM, in 294 repositories. 31 change documentation only.

An earlier version of this page, and the audit proposal built on it, said 58% of the fixes were in the provider-facing layer. That counted the five categories assigned from the title. Of the 900 fixes in them, 168 (19%) are not provider-facing when the diff is read, mostly from the errors category, whose title pattern matched "error", "fail" and "raise" with no LLM in the change. Read the 52% above instead.

Two categories are probably under-counted. **Errors, retries and limits** and **Parsing and validation** are small here because a fix that names a provider is drawn to **Provider API compatibility**; of the three hand-labelled errors fixes in the held-out 60, one was classified correctly and two as not provider-facing. Their real size is likely larger, and the counts above should not be read as their size.

## The named patterns

Specific shapes behind the categories, found by matching titles rather than diffs, so these counts are looser than the table above. Each is a mistake made independently by teams who never read each other's code.

| Pattern | Merged fixes | Repos | Rule |
| --- | --- | --- | --- |
| Defaults pointing at retired models | 97 | 61 | LDL007 |
| Unknown or unmapped finish / stop reasons | 75 | 31 | LDL014, LDL018 |
| Cache read and write tokens miscounted | 38 | 25 | LDL016 |
| Streamed parallel tool calls merged when the provider omits an index | 29 | 27 | LDL010 |
| Reasoning / thinking tokens missing from usage | 25 | 23 | LDL013 |
| Sampling parameters sent to Claude models that reject them | 24 | 17 | LDL001, LDL008 |
| Anthropic cumulative message_delta usage | 13 | 12 | LDL015 |
| Gemini responses with no content or blocked | 10 | 9 | LDL018 |
| Tool calls with empty or invalid JSON arguments | 5 | 5 | - *(no rule yet)* |

## What the distribution says

- The layer is not a Python problem. Of the 1,605 fixes, 527 are in Python repositories, 353 in Go, 224 in TypeScript, 136 in C# and 122 in Ruby. Tooling that only reads Python covers a third of where these bugs live.
- Provider API compatibility is the largest category by a margin: what a model accepts, what the response contains, and how the two drift apart between releases. It is also where the classifier is most likely to be reached for by a fix that belongs elsewhere.
- Retired model defaults is the one category that is a calendar, not a coding mistake: it recurs on the providers' schedule, which is why the retirement feed exists as a separate project.
- No lint rule covers: RAG and vector stores, Concurrency and async, Observability and tracing, Security. A static model-id check cannot reach them.
