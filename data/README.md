# Data

| File | What it is |
| --- | --- |
| `scored_snapshot_2026-11-19.json` | The static scoring of every merged fix as the corpus stood on 2026-11-19. The pool the 120-instance sample was drawn from. |
| `scored_snapshot_2026-11-20.json` | The same for 2026-11-20: 1,605 fixes with code, 1,349 usable, 960 usable in Go, Python or TypeScript. This is the frozen pool of the first run. |
| `CORPUS` | The exact `merge-log-data` commit the 2026-11-20 pool was scored from. |
| `sample_120.json` | The 120 instances of the random sample behind the first yield estimate. |
| `instances_2026-11-20.jsonl` | **The manifest: the 625 instances that reproduced.** One JSON object per line. |

## The manifest

An instance is a merged pull request whose test half fails at its base commit and passes with its
code half applied, each result repeated once. A line has:

| Field | Meaning |
| --- | --- |
| `instance_id` | `owner__repo-number` |
| `repo`, `pull_request`, `url`, `title` | The upstream pull request |
| `repo_language`, `runner_language`, `runner` | The repository's main language, the language of the test, and the runner used (`go test`, `pytest`, `vitest`, `jest`) |
| `category`, `repo_stars`, `code_lines_changed` | From the static scoring |
| `base_commit` | The base, as a 12-character prefix of the commit hash |
| `base_found_in` | `pull request branch` or `upstream default branch` (when the pull request's branch never had the preimage, see `RESULTS.md`) |
| `test_files` | The files of the change that are tests |
| `fail_kind` | `assertion`, `error`, or `no_tests_ran` (the test could not run at base; the weakest signal) |
| `tests_at_base`, `tests_with_fix` | Tests run and failed, without and with the fix |
| `repeated_on_both_sides` | Whether both results held on a second run (true for all 625) |

The manifest does not copy the patches. Each instance's diff is in
[`merge-log-data`](https://github.com/pcbeingused333/merge-log-data) at
`fixes/<owner>/<repo>/<number>.json`, which also records which files are tests. The base commit is
found by fetching `refs/pull/<number>/head` for `pull request branch` bases, or the upstream default
branch around the merge for the others. `scripts/reproduce.py` does exactly this.

**Licence.** The scripts are MIT. The manifest describes public pull requests; titles belong to their
authors. The diffs keep the licence of the project they come from.
