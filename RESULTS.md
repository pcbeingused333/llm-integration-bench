# Reproduction yield

Measured 2026-11-21 on the corpus as of 2026-11-20. Records: `results/pool_final_2026-11-20.json`
(one per instance, the retry pass applied over the first pass); raw runs in
`results/pool_2026-11-20.jsonl` and `results/pool_retry_2026-11-20.jsonl`; the tool versions of
the run in `results/pool_toolchain_2026-11-20.json`.

## Headline

**625 of the 960 usable Go, Python and TypeScript fixes (65.1%) can be turned into a runnable
instance:** at the pull request's base commit the test half of the change fails, with the code half
applied it passes, the runner's own test counts confirm that tests ran, and both results held on a
second run.

This is a census of the pool, not an estimate. The earlier random sample of 120 had predicted
68% (interval 59% to 75%); the same 120 on the final harness give 81 of 119 (68.1%,
interval 59% to 76%), and the full pool lands inside that interval. One of the 120 is
missing from the run because its repository's language label changed to "unknown" between two
corpus snapshots and it fell outside the Go, Python and TypeScript pool.

| Language | Whole pool | The 120-instance sample |
| --- | --- | --- |
| Go | 249 of 306 (81%) | 32 of 40 (80%) |
| Python | 256 of 451 (57%) | 26 of 41 (63%) |
| TypeScript | 120 of 203 (59%) | 23 of 38 (61%) |

The pool is the 960 fixes that the static scorer rated usable (`data/scored_snapshot_2026-11-20.json`)
out of the corpus's 1,605 fixes with code; the other usable fixes are in languages without a runner
here, such as C#, Ruby, Rust, Java and PHP.

## What the 625 instances are

- They span **151 repositories**. The five largest hold 17% of the instances and the ten
  largest 30%. 18 repositories have more than 10 instances; a cap of 10 per repository would
  remove 114 instances and leave 511.
- 571 fail at base by a failed assertion, 45 because no test could run at base and 9 by an import
  or build error. Of the 45, 42 are Go and 3 TypeScript, and almost all are a test that does not compile
  or resolve at base because it uses something the fix adds. They count only because the fix then makes
  the tests run, and are the weakest signal.
- All 625 were run twice on each side. None changed result, so none was flaky.
- Size of the code change shows no consistent trend in whether an instance reproduces:

| Code change | Reproduced |
| --- | --- |
| Under 20 lines | 361 of 584 (62%) |
| 20 to 59 lines | 204 of 274 (74%) |
| 60 to 149 lines | 47 of 84 (56%) |
| 150 lines or more | 13 of 18 (72%) |

| Category | Reproduced |
| --- | --- |
| Application logic | 151 of 284 (53%) |
| Streaming and tool calls | 133 of 171 (78%) |
| Provider API compatibility | 116 of 156 (74%) |
| Token usage and cost | 62 of 81 (77%) |
| Errors, retries and limits | 47 of 78 (60%) |
| Parsing and validation | 40 of 66 (61%) |
| Retired model defaults | 32 of 52 (62%) |
| Concurrency and async | 21 of 34 (62%) |

The manifest `data/instances_2026-11-20.jsonl` lists the 625 instances with their base commit, test files,
runner and counts. See `data/README.md`.

## The 335 that did not reproduce

| Count | Cause | Kind |
| --- | --- | --- |
| 183 | Other environment problems, not classified | open |
| 50 | A Python test dependency is missing | open, fixable per repository |
| 35 | A JavaScript package the test imports is not built | open, fixable per repository |
| 35 | Tests ran and still fail after the fix | real, possibly flaky or context-dependent |
| 9 | A workspace member is missing at the base commit | inherent |
| 8 | The test passes without the fix, so it does not catch the bug | not an instance |
| 7 | Test type with no runner here (Helm YAML) | inherent |
| 4 | Time limit exceeded | inherent to the limit |
| 4 | The change could not be isolated | method |

A retry of the 285 environment failures recovered **1**. Almost all are
deterministic rather than transient, so retrying is not worth the hours.

**They cluster by repository.** They sit in 140 repositories. In **24 repositories with three or more instances, every
instance failed, and together they hold 158 of the 335 failures (47%)**. The largest:

| Repository | Not reproduced |
| --- | --- |
| `Abilityai/trinity` | 15 of 15 |
| `posit-dev/pointblank` | 14 of 14 |
| `NPC-Worldwide/npcpy` | 13 of 13 |
| `temporalio/ai-integrations` | 11 of 11 |
| `jxxghp/MoviePilot` | 9 of 9 |
| `Mirascope/mirascope` | 9 of 24 |
| `GoDiao/dreamcoder` | 8 of 8 |
| `truera/trulens` | 7 of 7 |
| `rommapp/romm` | 7 of 7 |
| `i-am-bee/beeai-framework` | 6 of 21 |

That points at one preparation problem per repository (a test dependency that is not declared, a
package that has to be built first, a service the tests expect), not at the instances themselves.
Fixing those 24 repositories could recover up to 158 instances; how many it would really recover
depends on how many have a fix that a generic harness can apply, which is unmeasured. It is the
likeliest cheapest route above 65%.

## What this does not establish

- **Only the 625 that reproduced were run twice.** A flaky test among the failures may have turned a
  valid instance into a failure; that is unmeasured.
- **Failing at base is not proof that the test checks the intended behaviour.** It shows the test
  distinguishes the two states, which is the standard comparable benchmarks use.
- **Toolchain.** The run used go1.22.2 linux/amd64, Node v22.23.5, pnpm 12.21.0, uv 0.13.9, Python 3.12.3 on WSL 2
  with 8 cores. The earlier sample ran on Go 1.24, Node 22 and pnpm 10 and agrees, but outcomes depend on
  versions, so the toolchain file ships with the results.
- **Three runners.** About 390 usable instances are in languages with none.
- **Contamination is not measured.** These fixes are public and recent.
- **The sanitizer** that removes account names from error text also rewrote one legitimate
  directory called `home/...` in one message (docker/docker-agent#4924).

## How the harness decides

Validity comes from test counts parsed from machine-readable runner output, never from an exit code.
The change is isolated from the per-file patches GitHub recorded for each pull request, with the base
found by matching their preimage against real file contents, first on the pull request's branch and,
if the branch never had that state, on the upstream default branch just before the merge. The runner
is chosen by the test file's extension, and an allowlisted set of well-known test libraries may be
installed when a Python test cannot import them. `scripts/reproduce.py` has the details.
