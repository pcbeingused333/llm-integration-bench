# llm-integration-bench

Work in progress: a benchmark of LLM-integration bug fixes that upstream maintainers merged. What is
measured so far is the share that can be turned into a runnable instance (`RESULTS.md`); the
dataset itself has not been built yet.

## Working notes

A benchmark built from fixes that upstream maintainers merged, in the layer between
applications and LLM providers: streaming and tool calls, token and cost accounting, provider
API compatibility, retired model defaults, finish and stop reasons. The corpus is
[`merge-log-data`](https://github.com/pcbeingused333/merge-log-data): 1,488 merged pull requests in 369 repositories, with the diff of every one.

The point is the label. An instance is not "something that looked wrong to me", it is a change a
maintainer accepted, with the test that goes with it, in five languages.

## What counts as an instance

At the pull request's base commit:

```
base + test half of the change            ->  the test FAILS
base + test half + code half of the change ->  the test PASSES
```

That is the whole definition. Everything else is machinery to find out.

## Pipeline

| Step | Script | Output |
| --- | --- | --- |
| 1. Score every fix from its diff alone | `scripts/score_fixes.py` | `data/scored_*.json`: candidate / maybe / no, and why |
| 2. Reproduce a stratified sample | `scripts/reproduce.py` | one record per instance with the outcome |
| 3. Characterise the corpus | `scripts/taxonomy.py` | `taxonomy.md` |

Step 1 is cheap and static, and it removes what cannot work: no test in the diff, a test-only or
docs-only change, lockfiles or vendored trees, a test that needs a live provider credential.

## How the base is found

A pull request branch is not a clean base. The pipeline merges `main` into its branches, and
rebased branches carry `main`'s history on the first-parent line too. So `head^1` brings
unrelated changes (on `k8sgpt#1905` it brought 14 files for a 2-file fix). `reproduce.py`
isolates the change in one of two ways and accepts it only if its added and deleted lines match
the per-file counts GitHub recorded for the pull request, which is a check independent of the
git history:

1. a single commit whose own diff touches exactly the recorded files;
2. otherwise the run of commits at the branch tip, for as long as each commit touches only
   recorded files. The run ends at the first commit that touches anything else.

If neither matches the recorded counts the instance is rejected (`NO_FIX_COMMIT`) rather than
guessed.

## Outcomes, and why the exit code is not trusted

Validity is decided on test counts parsed from machine-readable runner output (`go test -json`,
pytest `--junitxml`, vitest and jest JSON), never on the exit code. A non-zero exit means a
failing assertion, a startup error, a bad flag and a missing dependency alike, and the harness
recorded exactly that mistake once: it passed vitest a reporter that vitest 4 had removed, vitest
died on startup, and four instances were reported as "the fix does not work" when no test had run.

| Outcome | Meaning |
| --- | --- |
| `REPRODUCED` | fails at base, passes with the fix, and tests demonstrably ran |
| `TEST_PASSES_AT_BASE` | the test does not catch the bug, so it is not an instance |
| `STILL_FAILS_AFTER_FIX` | tests ran and still failed after the fix |
| `RUNNER_ERROR` | no test ran, before or after: an environment problem, not a verdict |
| `NO_FIX_COMMIT` | history and the recorded line counts do not isolate the change |
| `SPLIT_FAIL` | the change has no test half or no code half |
| `APPLY_FAIL`, `SETUP_FAIL`, `NO_RUNNER`, `TIMEOUT` | plumbing |

A reproduced instance also records `fail_kind`, how it failed at base:

- `assertion`: the strongest signal, an assertion failed;
- `error`: the test imports or calls code that does not exist yet, an import or build error;
- `no_tests_ran`: nothing ran at base, credible only because the fix then makes tests run.

## What this does not yet establish

- **Yield is measured on a random sample of 120, not on the pool.** See `RESULTS.md` for the numbers, intervals and what is not established.
- **Triviality.** Most instances change fewer than 20 lines. Many are good, a small semantic fix
  under a large test. Some are a one-line default. A floor or a separate tier is a decision that
  has not been made.
- **Concentration.** C# candidates come from 3 repositories, Ruby from 7. A model can overfit to
  one code base and look good, so a per-repository cap is probably needed.
- **Flaky tests** are not yet detected: each side is run once.
- **Contamination.** These fixes are public and recent. Whether a given model has seen them is
  not measured here.
