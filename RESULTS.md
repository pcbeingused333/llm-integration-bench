# Reproduction yield: wave 1

Measured 2026-11-21. `scripts/reproduce.py`, `scripts/run_pool.py`; raw records in `results/wave1.json`.

## Corpus snapshot

Wave 1 sampled the corpus as it stood on **2026-11-19**: 1,488 merged pull requests, 1,494 fixes
with code, 898 usable in Go, Python or TypeScript. The corpus is rebuilt every six hours. On
2026-11-20 it held 1,599 merged and 1,605 fixes with code, of which 1,349 are usable and 960 are in
Go, Python or TypeScript. The 111 newer fixes were rescored: none of the earlier ones was dropped
and no earlier verdict changed. They were not part of the sample, so the figures below describe the
2026-11-19 pool. `data/scored_snapshot_2026-11-19.json` keeps that pool exactly.

## Headline

**81 of 120 randomly sampled instances reproduce: 68% (95% interval 59% to 75%).**

Reproduce means: at the pull request's base commit, the test half of the change fails, and with
the code half applied it passes, with the runner's own test counts confirming that tests ran.

| Language | Reproduced | Interval |
| --- | --- | --- |
| Go | 33 of 40 (82%) | 68% to 91% |
| Python | 24 of 40 (60%) | 45% to 74% |
| TypeScript | 24 of 40 (60%) | 45% to 74% |

Of the 81, 76 fail at base by a failed assertion and 5 by "no tests ran at base", which
counts only because the fix then makes tests run. One needed a missing test dependency installed
from a fixed allowlist. They span 54 repositories.

## What the sample is

Random, not chosen: 40 per language from the 898 instances that the static scorer rated `candidate`
or `maybe` in Go, Python or TypeScript, at most 3 per repository, seed 7. This matters because a
hand-picked sample of 14 that I built earlier reproduced 14 of 14, and a random sample of 6
reproduced 1. The difference was selection, not the harness.

Extrapolated with the per-language rates: about 605 reproducible of the 898 in the 2026-11-19 pool
(interval roughly 527 to 676), and about 645 of the 960 in the 2026-11-20 pool. That is an
estimate for this pipeline in this sandbox, not a property of the corpus, and it assumes the newer
fixes behave like the sampled ones, which is plausible (same pipeline) but not measured.

## Why the other 39 did not

| Count | Cause | Kind |
| --- | --- | --- |
| 20 | A long tail of environment problems, each different | open |
| 6 | Tests ran and still fail after the fix | real, possibly flaky or context-dependent |
| 3 | Test type with no runner here (Helm YAML) | inherent |
| 3 | Needs a private registry or a blocked host | inherent to the sandbox |
| 2 | A workspace member is missing at the base commit | inherent |
| 2 | Needs a toolchain not installed here (Node 24, bun) | inherent, fixable by installing it |
| 2 | Dependency install exceeds the time limit | inherent to the limit |
| 1 | Tests exceed the time limit | inherent to the limit |

The earlier category "history does not isolate the change" is gone. It was 15 instances (12%) and
came from inferring a pull request's change from commit structure. Isolation now applies the
per-file patches GitHub recorded and finds the base by matching their preimage against real file
contents, on the branch first and on the upstream default branch just before `merged_at` if the
branch never contained that state (merged pull requests are diffed against the base branch as it
was at merge time, which can be newer than the contributor's branch). All 15 resolve; 5 of them
now reproduce and the rest fall into the environment tail above. A regression check on 12
instances that already reproduced kept 12 of 12.

## Breakdowns, with the caveat that each cell is small

| Slice | Reproduced | Interval |
| --- | --- | --- |
| Scorer verdict `candidate` | 31 of 43 (72%) | 57% to 83% |
| Scorer verdict `maybe` | 50 of 77 (65%) | 54% to 75% |
| Code change under 20 lines | 55 of 81 (68%) | 57% to 77% |
| Code change 20 to 59 lines | 22 of 28 (79%) | 60% to 90% |
| Code change 60 lines or more | 4 of 11 (36%) | 15% to 65% |
| Streaming and tool calls | 23 of 28 (82%) | 64% to 92% |
| Provider API compatibility | 14 of 18 (78%) | 55% to 91% |
| Application logic | 25 of 42 (60%) | 44% to 73% |
| Repositories with 10k or more stars | 17 of 27 (63%) | 44% to 78% |
| Repositories under 10k stars | 64 of 93 (69%) | 59% to 77% |

- The static scorer predicts something but weakly: the `candidate` and `maybe` intervals overlap.
- **Large changes are not a reproducibility problem.** Before the isolation change 60 lines or
  more reproduced 0 of 11, which looked like a property of large fixes and was an artefact of the
  isolation. It is now 4 of 11. The interval is still wide.
- Small changes are not a reproducibility problem either. Whether to floor them is a design
  decision about difficulty, not about validity.
- Popular and small repositories reproduce at similar rates; the intervals overlap.

## What this does not establish

- **One run per side.** Flaky tests are not detected. An instance that passes once could fail on
  another run, and a failing-at-base result could be flakiness rather than the bug.
- **n = 120.** Language rates have intervals of about 25 points. The sample caps repositories at
  3, so the rates describe a more diverse draw than the pool, which is concentrated.
- **Only three runners.** C#, Ruby, Rust, Java and PHP, about 350 of the 1,249 usable instances on
  2026-11-19, have none here (`dotnet` is not installed).
- **Each instance was last run by the harness version current at that time.** Later versions
  only fixed things; the regression check found no loss, but the whole sample was not rerun on the
  final version.
- **Failing at base is not proof the test checks the intended behaviour.** It shows the test
  distinguishes the two states, which is the standard used by comparable benchmarks.
- **Contamination is not measured.** These fixes are public and recent.

## Harness changes made along the way (each from a failure this wave exposed)

Validity from parsed test counts rather than exit codes; the change isolated from GitHub's
recorded per-file patches; runner chosen by the test file's extension; nearest `go.mod`, `go.work`
and cgo for Go; `uv sync` from the owning package, with plugins, Python 3.12 preferred, and an
allowlisted dependency healer for Python; runner and build resolved from the test's package for JS,
with `engines.pnpm` pins honoured; one managed cache per toolchain, pnpm's store included, with a
disk floor of 10 GB.
