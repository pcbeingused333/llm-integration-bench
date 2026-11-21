#!/usr/bin/env python3
"""Try to turn a merged fix into a runnable benchmark instance, and say exactly why not.

An instance is valid only if, at the base commit of the pull request:
    base + test-part-of-diff            -> the test FAILS
    base + test-part + code-part        -> the test PASSES
That is the whole definition. Everything else here is plumbing to find out.

The base commit comes from GitHub's own `refs/pull/N/merge` ref, whose first parent is the
tip of the base branch when the pull request was open and whose second parent is the PR
head. One fetch gives us both sides, so we never guess the base.

Outcomes, which matter as much as the pass count:
    REPRODUCED              fails before, passes after: a valid instance
    TEST_PASSES_AT_BASE     the test does not actually catch the bug (not an instance)
    STILL_FAILS_AFTER_FIX   the fix alone does not make it pass (needs more of the PR, or env)
    NO_FIX_COMMIT           no commits on the branch isolate the PR's recorded change
    SPLIT_FAIL              the fix commit does not contain both a test half and a code half
    APPLY_FAIL              the split diff does not apply to the base tree
    RUNNER_ERROR            no test ran, before or after: an environment problem, not a verdict
    FLAKY                   reproduced once, but the result did not repeat on a second run
    SETUP_FAIL              dependencies could not be resolved at the base commit
    NO_RUNNER               no test command could be determined for this project
    TIMEOUT

Usage: reproduce.py <merge-log-data> <sample.json> <workdir> <out.json>
"""
from __future__ import annotations

import json
import re
import os
import shutil
import subprocess
import sys
import time

CLONE_T, SETUP_T, TEST_T, BUILD_T = 600, 1500, 600, 900
FLAKE_CHECK = os.environ.get("REPRO_FLAKE", "1") == "1"
OUTFILE = ""


def run(cmd, cwd=None, timeout=300, env=None):
    e = dict(os.environ)
    e.update(env or {})
    e.setdefault("GIT_TERMINAL_PROMPT", "0")
    try:
        p = subprocess.run(cmd, cwd=cwd, timeout=timeout, env=e, shell=isinstance(cmd, str),
                           capture_output=True, text=True, errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


def numstat(dest, base, head, files):
    rc, out = run(["git", "diff", "--numstat", base, head, "--"] + list(files), cwd=dest)
    if rc != 0:
        return None
    stat = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            stat[parts[2]] = (int(parts[0]), int(parts[1]))
    return stat


def resolve_instance(repo, number, dest, recorded_files, merged_at=None):
    """Find the base and head that isolate exactly this pull request's change.

    The pull request branch is not a clean base: the pipeline merges `main` into its own
    branches, so the head's first parent carries unrelated drift (on k8sgpt#1905 it brought 14
    files instead of 2). Two strategies, both checked against the line counts GitHub recorded
    per file for the pull request, which is an oracle independent of the git history:

    1. a single commit whose own diff touches exactly the recorded file set (squashed PRs);
    2. otherwise the run of commits at the branch tip, walked with --first-parent so that
       commits arriving through merges of `main` are excluded, for as long as every file a
       commit touches is one the pull request recorded. The run stops at the first commit
       that touches anything else, which is where the branch's own work ends and `main`'s
       history begins (on a rebased branch that history is on the first-parent line too).
       Base is the parent of the oldest commit in the run, head is the branch tip.

    An instance is returned only if its added and deleted lines match the recorded ones, file
    by file, within a small tolerance (see `faithful`). Beyond it, history and record disagree
    and the instance is not trusted.
    """
    url = f"https://github.com/{repo}"
    os.makedirs(dest, exist_ok=True)
    run(["git", "init", "-q"], cwd=dest)
    run(["git", "remote", "add", "origin", url], cwd=dest)
    rc, _ = run(["git", "fetch", "-q", "--depth", "150", "origin",
                 f"refs/pull/{number}/head"], cwd=dest, timeout=CLONE_T)
    if rc != 0:
        return None, None, "pull/N/head could not be fetched", None
    run(["git", "update-ref", "refs/prhead", "FETCH_HEAD"], cwd=dest)

    by_patches = resolve_by_patches(dest, recorded_files)
    if by_patches:
        sha, texts, how = by_patches
        return sha, "FETCH_HEAD", how, texts
    if merged_at:
        upstream = resolve_on_upstream(dest, recorded_files, merged_at)
        if upstream:
            sha, texts, how = upstream
            return sha, "FETCH_HEAD", how, texts

    want = {f["filename"]: (f.get("additions", 0), f.get("deletions", 0)) for f in recorded_files}
    names = set(want)

    def faithful(base, head, files):
        """(ok, drift): do the line counts match the recorded ones, within a small tolerance?

        Drift is the total absolute difference in added and deleted lines. A few lines of it
        are expected (a line `main` gained identically, a file GitHub counted at another
        moment) and the test, not this check, decides validity. Large drift means unrelated
        history came along, and the instance is refused. The value is recorded either way.
        """
        got = numstat(dest, base, head, files)
        if got is None:
            return False, None
        drift = sum(abs(got.get(k, (0, 0))[0] - want[k][0]) + abs(got.get(k, (0, 0))[1] - want[k][1])
                    for k in files if k in want)
        total = sum(want[k][0] + want[k][1] for k in files if k in want)
        return drift <= max(2, int(0.05 * total)), drift

    rc, out = run(["git", "rev-list", "--no-merges", "--max-count=60", "refs/prhead"], cwd=dest)
    if rc != 0:
        return None, None, "history of the pull request head is unreadable", None
    for sha in out.split():
        rc, ns = run(["git", "diff", "--name-only", sha + "^", sha], cwd=dest)
        if rc == 0 and set(ns.split()) == names:
            ok, drift = faithful(sha + "^", sha, names)
            if ok:
                return sha + "^", sha, f"single commit, file set matches, line drift {drift}", None

    rc, out = run(["git", "rev-list", "--first-parent", "--no-merges", "--max-count=60",
                   "refs/prhead"], cwd=dest)
    run_of_pr = []
    for sha in out.split():
        rc, ns = run(["git", "diff", "--name-only", sha + "^", sha], cwd=dest)
        if rc != 0:
            break
        touched = set(ns.split())
        if not touched:
            continue
        if not touched <= names:
            break
        run_of_pr.append(sha)
    if run_of_pr:
        base, head = run_of_pr[-1] + "^", "refs/prhead"
        ok, drift = faithful(base, head, names)
        if ok:
            return base, head, f"{len(run_of_pr)} commits at the branch tip, line drift {drift}", None
        return None, None, (f"candidate range found but its line counts differ from the "
                            f"recorded ones by {drift} lines: history and record disagree"), None
    return None, None, "no commit at the branch tip stays within the recorded files", None


def split_diff(dest, base, head, test_files, files):
    """The change restricted to the recorded files, split into its test half and code half."""
    tset = set(test_files)
    tests = [f for f in files if f in tset]
    code = [f for f in files if f not in tset]
    if not tests or not code:
        return None, None
    rc1, tp = run(["git", "diff", base, head, "--"] + tests, cwd=dest)
    rc2, cp = run(["git", "diff", base, head, "--"] + code, cwd=dest)
    if rc1 != 0 or rc2 != 0 or not tp.strip() or not cp.strip():
        return None, None
    return tp, cp



# ---- isolating the change from GitHub's recorded per-file patches -------------------------
# Inferring the change from commit structure fails on merges of main, rebased branches and
# squashes (12% of wave 1). GitHub recorded each file's patch for the pull request, and that
# patch is exactly the change. Its preimage (context and deleted lines, at their old line
# numbers) can be checked against the real file at any ancestor of the branch, so the base is
# found by content, not by guessing which commits belong to the pull request.

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def preimage_hunks(patch):
    """[(old_start, [old lines])] from a unified-diff body, or None if it is not parseable."""
    hunks, cur = [], None
    # split on "\n" only: str.splitlines() also splits on form feeds and unicode separators
    # that real source files contain, which would shift every line after them.
    for line in patch.split("\n"):
        mo = HUNK.match(line)
        if mo:
            cur = [int(mo.group(1)), []]
            hunks.append(cur)
        elif cur is None:
            return None
        elif line.startswith("\\"):
            continue
        elif line[:1] in (" ", "-"):
            cur[1].append(line[1:])
        elif line[:1] == "+":
            continue
        elif line == "":
            cur[1].append("")
        else:
            return None
    return [(a, b) for a, b in hunks]


def patch_text(f):
    """A git-applicable patch for one recorded file entry, or None if it cannot be built."""
    body, name, status = f.get("patch"), f["filename"], f.get("status")
    if not body or status not in ("modified", "added", "removed"):
        return None
    old = "/dev/null" if status == "added" else f"a/{name}"
    new = "/dev/null" if status == "removed" else f"b/{name}"
    head = f"diff --git a/{name} b/{name}\n"
    if status == "added":
        head += "new file mode 100644\n"
    if status == "removed":
        head += "deleted file mode 100644\n"
    return head + f"--- {old}\n+++ {new}\n" + body.rstrip("\n") + "\n"


def preimage_matches(dest, sha, f):
    """Does file `f`'s recorded preimage match the file as it is at commit `sha`?"""
    name, status = f["filename"], f.get("status")
    rc, content = run(["git", "show", f"{sha}:{name}"], cwd=dest)
    if status == "added":
        return rc != 0
    if rc != 0:
        return False
    hunks = preimage_hunks(f.get("patch") or "")
    if not hunks:
        return False
    lines = content.split("\n")
    for start, old in hunks:
        if [l.rstrip("\r") for l in lines[start - 1:start - 1 + len(old)]] != \
                [l.rstrip("\r") for l in old]:
            return False
    return True


def resolve_on_upstream(dest, recorded, merged_at):
    """Fallback: look for the base in the upstream default branch just before the merge.

    GitHub computes a merged pull request's recorded diff against the base branch as it was at
    merge time, which can be newer than any state the contributor's branch ever contained (the
    branch was last synced weeks earlier). The recorded preimage then exists only on the
    upstream branch. We fetch that branch from shortly before `merged_at` and take the newest
    commit not after the merge whose content matches every recorded preimage: the state just
    before the change landed.
    """
    import datetime as _dt
    try:
        t = _dt.datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    since = (t - _dt.timedelta(days=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    until = (t + _dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rc, _ = run(["git", "fetch", "-q", f"--shallow-since={since}", "origin", "HEAD"],
                cwd=dest, timeout=CLONE_T)
    if rc != 0:
        return None
    texts = {}
    for f in recorded:
        t_ = patch_text(f)
        if t_ is None:
            return None
        texts[f["filename"]] = t_
    rc, out = run(["git", "rev-list", "--first-parent", f"--before={until}", "--max-count=500",
                   "FETCH_HEAD"], cwd=dest)
    if rc != 0:
        return None
    for i, sha in enumerate(out.split()):
        if all(preimage_matches(dest, sha, f) for f in recorded):
            return sha, texts, f"upstream default branch, {i} commits before the merge"
    return None


def resolve_by_patches(dest, recorded):
    """(base sha, {filename: patch text}, how) or None.

    Walks the branch's first-parent line from the tip downward; the first commit whose content
    matches every recorded preimage is the base. Going down from the tip, commits that already
    contain part of the change do not match, so the first match is the state just before it.
    """
    texts = {}
    for f in recorded:
        t = patch_text(f)
        if t is None or preimage_hunks(f.get("patch") or "") is None and f.get("status") != "added":
            return None
        texts[f["filename"]] = t
    rc, out = run(["git", "rev-list", "--first-parent", "--max-count=140", "refs/prhead"], cwd=dest)
    if rc != 0:
        return None
    for i, sha in enumerate(out.split()):
        if all(preimage_matches(dest, sha, f) for f in recorded):
            return sha, texts, f"recorded patches, base {i} commits below the tip"
    return None


def revert_patch(dest, patch, tag):
    path = os.path.join(dest, f".instance-{tag}-revert.patch")
    open(path, "w").write(patch)
    rc, out = run(["git", "apply", "-R", "--whitespace=nowarn", path], cwd=dest)
    return rc == 0, out


def apply_patch(dest, patch, tag):
    path = os.path.join(dest, f".instance-{tag}.patch")
    open(path, "w").write(patch)
    for extra in ([], ["-3"]):
        rc, out = run(["git", "apply", "--whitespace=nowarn"] + extra + [path], cwd=dest)
        if rc == 0:
            return True, ""
    return False, out



# ---- evidence that tests actually ran ----------------------------------------------------
# A non-zero exit code proves nothing: a startup error, a bad flag, an import failure in the
# runner and a genuinely failing assertion all look the same. Validity is therefore decided on
# counts parsed from machine-readable runner output, never on the exit code alone.

def parse_go(out):
    tests, pkg_fail, build_fail = {}, False, False
    notes = []
    for line in out.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            if "build failed" in line or "setup failed" in line:
                build_fail = True
            if line.strip():
                notes.append(line.strip())
            continue
        if not ev.get("Test") and ev.get("Action") in ("output", "build-output"):
            text = ev.get("Output", "").strip()
            if text and not text.startswith(("ok ", "?", "=== ", "--- ", "PASS")):
                notes.append(text)
            if ev.get("Action") == "build-output":
                build_fail = True
        action, name = ev.get("Action"), ev.get("Test")
        if name and action in ("pass", "fail", "skip"):
            tests[name] = action
        elif not name and action == "fail":
            pkg_fail = True
        text = ev.get("Output", "")
        if "[build failed]" in text or "[setup failed]" in text:
            build_fail = True
    failed = len([v for v in tests.values() if v == "fail"])
    return dict(ran=len([v for v in tests.values() if v != "skip"]), failed=failed,
                errored=build_fail or (pkg_fail and failed == 0),
                why=" | ".join(notes)[:420])


def parse_junit(path):
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return dict(ran=0, failed=0, errored=True)
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    n = sum(int(s.get("tests", 0)) for s in suites)
    skipped = sum(int(s.get("skipped", 0)) for s in suites)
    why = ""
    for node in root.iter():
        if node.tag in ("error", "failure"):
            why = " ".join(((node.get("message") or "") + " " + (node.text or "")).split())[:420]
            break
    return dict(ran=n - skipped, failed=sum(int(s.get("failures", 0)) for s in suites),
                errored=sum(int(s.get("errors", 0)) for s in suites) > 0, why=why)


def parse_js_json(path):
    try:
        d = json.load(open(path))
    except Exception:
        return dict(ran=0, failed=0, errored=True)
    why = ""
    for t in d.get("testResults", []):
        if t.get("message"):
            why = " ".join(t["message"].split())[:420]
            break
    return dict(ran=d.get("numTotalTests", 0) - d.get("numPendingTests", 0),
                failed=d.get("numFailedTests", 0),
                errored=d.get("numFailedTestSuites", 0) > 0 and d.get("numFailedTests", 0) == 0,
                why=why)



# Test dependencies a project may use without declaring them where uv looks (poetry groups,
# requirements files). Healing installs a missing module from PyPI, which is a supply-chain
# risk if the name comes from untrusted code: an import of a private or invented module name
# would install whatever a stranger registered under it. So only well-known libraries are ever
# installed this way, by an explicit list, and the record says which were.
HEALABLE = {
    "fakeredis": "fakeredis", "sqlalchemy": "sqlalchemy", "requests_mock": "requests-mock",
    "responses": "responses", "respx": "respx", "httpx": "httpx", "freezegun": "freezegun",
    "faker": "faker", "hypothesis": "hypothesis", "pytest_mock": "pytest-mock", "mock": "mock",
    "aiohttp": "aiohttp", "anyio": "anyio", "trio": "trio", "numpy": "numpy", "pandas": "pandas",
    "pydantic": "pydantic", "yaml": "PyYAML", "dotenv": "python-dotenv", "PIL": "Pillow",
    "bs4": "beautifulsoup4", "redis": "redis", "psycopg2": "psycopg2-binary",
    "pymongo": "pymongo", "boto3": "boto3", "moto": "moto", "docker": "docker",
    "jinja2": "jinja2", "tomli": "tomli", "dateutil": "python-dateutil", "pytz": "pytz",
    "attr": "attrs", "orjson": "orjson", "websockets": "websockets", "uvicorn": "uvicorn",
    "fastapi": "fastapi", "starlette": "starlette", "flask": "flask", "jwt": "PyJWT",
    "tenacity": "tenacity", "tiktoken": "tiktoken", "openai": "openai", "anthropic": "anthropic",
    "pytest_asyncio": "pytest-asyncio", "pytest_httpx": "pytest-httpx", "vcr": "vcrpy",
    "aioresponses": "aioresponses", "numpy": "numpy", "scipy": "scipy", "tqdm": "tqdm",
    "httpcore": "httpcore", "h11": "h11", "sniffio": "sniffio", "certifi": "certifi",
    "idna": "idna", "jsonschema": "jsonschema", "markupsafe": "markupsafe", "werkzeug": "werkzeug",
    "rich": "rich", "click": "click", "typer": "typer", "cachetools": "cachetools",
}

def run_tests(kind, argv, env, dest, outfile):
    """Run once and return (exit code, evidence, tail of output)."""
    if os.path.exists(outfile):
        os.remove(outfile)
    rc, out = run(argv, cwd=dest, timeout=TEST_T, env=env)
    if rc != 0 and kind == "pytest" and "unrecognized arguments" in out:
        argv = [a.replace("-m pytest -q", "-m pytest -q -o addopts=") for a in argv]
        rc, out = run(argv, cwd=dest, timeout=TEST_T, env=env)
    if rc == 124:
        return rc, None, "TIMEOUT"
    if kind == "go":
        ev = parse_go(out)
    elif kind == "pytest":
        ev = parse_junit(outfile)
        healed = []
        venv = env.get("UV_PROJECT_ENVIRONMENT")
        while venv and rc != 0 and ev["ran"] <= 1 and len(healed) < 4:
            import re as _re
            mo = _re.search(r"No module named '([A-Za-z0-9_]+)", out + " " + ev.get("why", ""))
            top = mo.group(1) if mo else None
            if not top or top in healed or top not in HEALABLE:
                break
            run(["uv", "pip", "install", "-q", "--python", venv + "/bin/python", HEALABLE[top]],
                timeout=300, env=env)
            healed.append(top)
            if os.path.exists(outfile):
                os.remove(outfile)
            rc, out = run(argv, cwd=dest, timeout=TEST_T, env=env)
            if rc == 124:
                return rc, None, "TIMEOUT"
            ev = parse_junit(outfile)
        if healed:
            ev["healed"] = healed
    else:
        ev = parse_js_json(outfile)
    return rc, ev, out[-900:]

# ---- per-language setup and test command -------------------------------------------------

def setup_go(dest, test_file, cache):
    """Go repos can hold several modules (agentfield keeps its SDK in sdk/go), so the module is
    the nearest go.mod above the test file, not whatever sits at the repository root."""
    # GOCACHE inside the managed cache: the default (~/.cache/go-build) grew to 9.6 GB outside
    # anything the pool runner watches or clears.
    env = {"GOMODCACHE": cache, "GOCACHE": cache + "-build", "CGO_ENABLED": "1"}
    if not os.path.exists(os.path.join(dest, "go.work")):
        env["GOFLAGS"] = "-mod=mod"
    test_dir = os.path.dirname(test_file)
    mod_dir, probe = None, test_dir
    while True:
        if os.path.exists(os.path.join(dest, probe, "go.mod")):
            mod_dir = probe
            break
        if not probe:
            break
        probe = os.path.dirname(probe)
    if mod_dir is None:
        return False, "no go.mod at or above the test file", None
    rel = os.path.relpath(test_dir or ".", mod_dir or ".")
    pkg = "." if rel == "." else "./" + rel
    rc, out = run(["go", "-C", mod_dir or ".", "mod", "download"], cwd=dest, timeout=SETUP_T, env=env)
    return rc == 0, out, ("go", ["go", "-C", mod_dir or ".", "test", "-count=1", "-json", pkg], env, None)


def uv_for(dest, cache):
    """The uv binary a project insists on, if it pins one (`required-version` in pyproject.toml
    or uv.toml). uv refuses to run under another version, so the pinned one is installed once
    into the shared cache and used for that instance only."""
    import re as _re
    pin = None
    for name in ("pyproject.toml", "uv.toml"):
        p = os.path.join(dest, name)
        if os.path.exists(p):
            mo = _re.search(r'required-version\s*=\s*"([^"]+)"', open(p, errors="replace").read())
            if mo:
                pin = mo.group(1)
                break
    if not pin:
        return "uv", {}
    rc, out = run(["uv", "--version"])
    ver = out.split()[1] if rc == 0 and len(out.split()) > 1 else ""
    exact = pin.lstrip("=<>~! ")
    if ver and ("==" in pin and ver == exact):
        return "uv", {}
    venv = os.path.join(cache, f"uv-{exact}")
    if not os.path.exists(os.path.join(venv, "bin", "uv")):
        run(["python3", "-m", "venv", venv], timeout=120)
        run([os.path.join(venv, "bin", "pip"), "install", "-q", f"uv{pin}"], timeout=300)
    binp = os.path.join(venv, "bin", "uv")
    return (binp, {}) if os.path.exists(binp) else ("uv", {})


def setup_python(dest, test_file, cache):
    """Python projects keep their test dependencies in extras, in PEP 735 dependency groups, in
    workspace members and sometimes in a subdirectory, so the install is `uv sync` run from the
    package that owns the test, with every extra and group. Two fallbacks follow: without
    installing the project itself (flat-layout setuptools projects cannot be installed
    editable, and their tests import the source in place), and the older pip-style install.
    Plugins that projects reference from their pytest `addopts` (xdist, cov, rerunfailures) are
    installed up front; anything still unrecognised is dropped in run_tests."""
    import shlex
    uv, _ = uv_for(dest, cache)
    venv = os.path.join(dest, ".venv")
    env = {"UV_CACHE_DIR": cache, "UV_LINK_MODE": "copy", "UV_PROJECT_ENVIRONMENT": venv}

    pkg = os.path.dirname(test_file)
    while pkg and not any(os.path.exists(os.path.join(dest, pkg, f))
                          for f in ("pyproject.toml", "setup.py", "setup.cfg")):
        pkg = os.path.dirname(pkg)
    pkg_abs = os.path.join(dest, pkg) if pkg else dest
    python_path = []

    logs = []
    synced = False
    for pyflag in (["--python", "3.12"], []):
        for extra in ([], ["--no-install-project"]):
            rc, out = run([uv, "sync", "--all-extras", "--all-groups"] + pyflag + extra,
                          cwd=pkg_abs, timeout=SETUP_T, env=env)
            logs.append(out[-600:])
            if rc == 0:
                synced = True
                if extra:
                    python_path = [pkg_abs, os.path.join(pkg_abs, "src")]
                break
        if synced:
            break
    if not synced:
        run([uv, "venv", "-q", venv], cwd=dest, timeout=300, env=env)
        for spec in ('.[dev,test]', '.[dev]', '.[test]', '.'):
            rc, out = run([uv, "pip", "install", "-q", "-e", spec, "--python", venv + "/bin/python"],
                          cwd=pkg_abs, timeout=SETUP_T, env=env)
            logs.append(out[-600:])
            if rc == 0:
                synced = True
                break
    if not synced:
        return False, "\n".join(logs)[-900:], None

    run([uv, "pip", "install", "-q", "--python", venv + "/bin/python", "pytest", "pytest-asyncio",
         "pytest-xdist", "pytest-cov", "pytest-rerunfailures", "pytest-mock"],
        cwd=pkg_abs, timeout=600, env=env)
    if python_path:
        env["PYTHONPATH"] = os.pathsep.join(python_path)
    rel = os.path.relpath(test_file, pkg or ".")
    script = (f"cd {shlex.quote(pkg_abs)} && {shlex.quote(venv + '/bin/python')} -m pytest -q "
              f"-p no:cacheprovider --junitxml={shlex.quote(OUTFILE)} {shlex.quote(rel)}")
    return True, "\n".join(logs)[-300:], ("pytest", ["sh", "-c", script], env, None)


def pnpm_bin(dest):
    """pnpm itself, or the exact version a project pins in `engines.pnpm`, which pnpm enforces
    even with engine-strict off (umami pins 12.3.4)."""
    try:
        pin = (json.load(open(os.path.join(dest, "package.json"))).get("engines") or {}).get("pnpm")
    except (OSError, ValueError):
        pin = None
    if pin and pin[:1].isdigit() and all(c.isdigit() or c == "." for c in pin):
        return ["npx", "-y", f"pnpm@{pin}"]
    return ["pnpm"]


def build_cmds(dest, package_json_text, test_file):
    """Candidate builds, cheapest first. The package that owns the test needs its workspace
    dependencies built, not the whole monorepo: `pnpm --filter "<pkg>^..." run build` builds
    only those (8 s on TanStack/ai, where the root build fails). The root build follows as a
    fallback for repos whose tests need something the filtered build does not produce."""
    try:
        root_scripts = json.loads(package_json_text).get("scripts") or {}
    except ValueError:
        root_scripts = {}
    pnpm = os.path.exists(os.path.join(dest, "pnpm-lock.yaml"))
    cmds = []
    probe = os.path.dirname(test_file)
    while probe:
        pj = os.path.join(dest, probe, "package.json")
        if os.path.exists(pj):
            try:
                name = json.load(open(pj)).get("name")
            except ValueError:
                name = None
            if name and pnpm:
                cmds.append(pnpm_bin(dest) + ["--filter", f"{name}^...", "run", "build"])
            break
        probe = os.path.dirname(probe)
    if "build" in root_scripts:
        if pnpm:
            cmds.append(pnpm_bin(dest) + ["run", "build"])
        elif os.path.exists(os.path.join(dest, "yarn.lock")):
            cmds.append(["npx", "-y", "yarn@1", "build"])
        else:
            cmds.append(["npm", "run", "build"])
    return cmds or None


def setup_node(dest, test_file, cache):
    env = {"npm_config_cache": cache, "CI": "1", "HUSKY": "0", "npm_config_engine_strict": "false",
           "npm_config_store_dir": os.path.join(cache, "pnpm-store"),
           "YARN_CACHE_FOLDER": os.path.join(cache, "yarn")}
    mgr = None
    if os.path.exists(os.path.join(dest, "pnpm-lock.yaml")):
        # pnpm 10 ignores npm_config_store_dir; without an explicit store its global store grew
        # to 12 GB outside the managed cache and filled the disk twice.
        mgr = pnpm_bin(dest) + ["install", "--ignore-scripts", "--reporter=append-only",
                                "--store-dir", os.path.join(cache, "pnpm-store")]
    elif os.path.exists(os.path.join(dest, "yarn.lock")):
        mgr = ["npx", "-y", "yarn@1", "install", "--ignore-scripts", "--ignore-engines"]
    else:
        mgr = ["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"]
    rc, out = run(mgr, cwd=dest, timeout=SETUP_T, env=env)
    if rc != 0:
        return False, out[-2500:], None
    # The runner belongs to the package that owns the test, which in a monorepo is not the
    # root: argent's vitest lives in packages/tool-server. Look from the test's directory
    # upward, take the first package.json or config that names a runner, and run from there.
    import shlex
    probe, found = os.path.dirname(test_file), None
    while True:
        d = os.path.join(dest, probe)
        pj = os.path.join(d, "package.json")
        text = open(pj, errors="replace").read() if os.path.exists(pj) else ""
        cfgs = [f for f in os.listdir(d) if f.startswith(("vitest.config", "vite.config",
                                                          "jest.config"))] if os.path.isdir(d) else []
        if "vitest" in text or any(c.startswith(("vitest", "vite.")) for c in cfgs):
            found = ("vitest", probe, text)
            break
        if "jest" in text or any(c.startswith("jest") for c in cfgs):
            found = ("jest", probe, text)
            break
        if not probe:
            break
        probe = os.path.dirname(probe)
    root_txt = open(os.path.join(dest, "package.json"), errors="replace").read() \
        if os.path.exists(os.path.join(dest, "package.json")) else ""
    if found:
        kind, pkgdir, _ = found
        rel = os.path.relpath(test_file, pkgdir or ".")
        flags = (f"run --reporter=json --outputFile={shlex.quote(OUTFILE)}" if kind == "vitest"
                 else f"--json --outputFile={shlex.quote(OUTFILE)}")
        script = f"cd {shlex.quote(pkgdir or '.')} && npx -y {kind} {flags} {shlex.quote(rel)}"
        return True, out[-500:], (kind, ["sh", "-c", script], env,
                                  build_cmds(dest, root_txt, test_file))
    scripts = {}
    try:
        scripts = json.loads(root_txt).get("scripts") or {}
    except ValueError:
        pass
    return False, f"unsupported test runner; root scripts.test = {scripts.get('test')!r}", None


SETUPS = {"Go": setup_go, "Python": setup_python, "TypeScript": setup_node,
          "JavaScript": setup_node}


def one(inst, root, workdir, caches):
    repo, number, lang = inst["repo"], inst["number"], inst["lang"]
    rec = dict(repo=repo, number=number, lang=lang, title=inst["title"],
               url=inst.get("url"), outcome=None, detail="", seconds=0)
    t0 = time.time()
    dest = os.path.join(workdir, repo.replace("/", "__") + f"-{number}")
    shutil.rmtree(dest, ignore_errors=True)
    try:
        fx = json.load(open(os.path.join(root, f"fixes/{repo}/{number}.json")))
        test_files = fx.get("test_files") or []

        recorded = fx.get("files") or []
        want_files = [f["filename"] for f in recorded]
        base, head, how, texts = resolve_instance(repo, number, dest, recorded, fx.get("merged_at"))
        if not base:
            rec.update(outcome="NO_FIX_COMMIT", detail=how)
            return rec
        rec["resolved_by"] = how

        if texts:
            tset = set(test_files)
            test_patch = "".join(t for n, t in texts.items() if n in tset)
            code_patch = "".join(t for n, t in texts.items() if n not in tset)
            if not test_patch or not code_patch:
                test_patch = code_patch = None
        else:
            test_patch, code_patch = split_diff(dest, base, head, test_files, want_files)
        if not test_patch or not code_patch:
            rec.update(outcome="SPLIT_FAIL", detail=f"no test half or no code half: "
                       f"files={want_files} test_files={test_files}")
            return rec

        rc, sha = run(["git", "rev-parse", base], cwd=dest)
        rec["base"] = sha.strip()[:12]
        rc, _ = run(["git", "checkout", "-q", "-f", base], cwd=dest)
        if rc != 0:
            rec.update(outcome="NO_BASE", detail="base commit not checkoutable (shallow)")
            return rec

        ok, err = apply_patch(dest, test_patch, "test")
        if not ok:
            rec.update(outcome="APPLY_FAIL", detail="test patch: " + err[-400:])
            return rec

        # The runner follows the test, not the repository: a Go repo can keep Python SDK tests,
        # and a Helm chart's YAML tests have no runner here at all.
        by_ext = {".go": ("Go", setup_go), ".py": ("Python", setup_python),
                  ".ts": ("TypeScript", setup_node), ".tsx": ("TypeScript", setup_node),
                  ".js": ("TypeScript", setup_node), ".jsx": ("TypeScript", setup_node),
                  ".mjs": ("TypeScript", setup_node), ".mts": ("TypeScript", setup_node)}
        usable = [t for t in test_files if os.path.splitext(t)[1].lower() in by_ext]
        if not usable:
            exts = sorted({os.path.splitext(t)[1] or t for t in test_files})
            rec.update(outcome="NO_RUNNER", detail=f"no runner for test files of type {exts}")
            return rec
        test_files = usable
        lang, setup = by_ext[os.path.splitext(test_files[0])[1].lower()]
        rec["runner_lang"] = lang
        global OUTFILE
        OUTFILE = os.path.join(os.path.dirname(dest), "." + os.path.basename(dest) + "-result")
        ok, log, cmd = setup(dest, test_files[0], caches.get(lang) or caches["Python"])
        if not ok or cmd is None:
            rec.update(outcome="SETUP_FAIL", detail=(log or "")[-600:])
            return rec
        kind, argv, env, build = cmd
        rec["cmd"] = " ".join(argv)

        rc_b, ev_b, tail_b = run_tests(kind, argv, env, dest, OUTFILE)
        # A test that cannot even load (a workspace package imported as built, a generated
        # module) is not a verdict. Build lazily, only when that is what happened, and again
        # after the fix is applied, because the fix may change what the test imports.
        built = False
        built_with = None
        if (build and ev_b is not None and rc_b != 0 and ev_b["ran"] == 0 and ev_b["errored"]):
            tried = []
            for cand in build:
                brc, bout = run(cand, cwd=dest, timeout=BUILD_T, env=env)
                tried.append(dict(cmd=" ".join(cand), rc=brc))
                if brc == 0:
                    built_with = cand
                    break
            rec["build"] = tried
            built = True
            rc_b, ev_b, tail_b = run_tests(kind, argv, env, dest, OUTFILE)
        if ev_b is None:
            rec.update(outcome="TIMEOUT", detail="test run before the fix timed out")
            return rec
        rec["before"] = dict(rc=rc_b, **ev_b)
        if rc_b == 0:
            if ev_b["ran"] == 0:
                rec.update(outcome="RUNNER_ERROR", detail="exit 0 but no test ran at base")
            else:
                rec.update(outcome="TEST_PASSES_AT_BASE",
                           detail="test passes without the fix, so it does not catch the bug")
            return rec
        # Non-zero at base. What KIND of failure matters for how the instance can be used:
        # an assertion is the strongest signal; an import or build error because the new test
        # references code that does not exist yet is legitimate but weaker; and "no tests ran"
        # is only credible if the fix then makes tests run, which the next step decides.
        rec["fail_kind"] = ("assertion" if ev_b["failed"] > 0
                            else "error" if ev_b["ran"] > 0 else "no_tests_ran")

        ok, err = apply_patch(dest, code_patch, "code")
        if not ok:
            rec.update(outcome="APPLY_FAIL", detail="code patch: " + err[-400:])
            return rec

        if built_with:
            run(built_with, cwd=dest, timeout=BUILD_T, env=env)
        rc_a, ev_a, tail_a = run_tests(kind, argv, env, dest, OUTFILE)
        if ev_a is None:
            rec.update(outcome="TIMEOUT", detail="test run after the fix timed out")
            return rec
        rec["after"] = dict(rc=rc_a, **ev_a)
        if rc_a == 0 and ev_a["ran"] > 0:
            rec.update(outcome="REPRODUCED", detail="fails at base, passes with the fix")
            if FLAKE_CHECK:
                # A result seen once is not yet a result. Run the fixed state again, then take
                # the code half back out and run the base again: both must repeat. Anything
                # that does not is flaky and is not an instance.
                rc_a2, ev_a2, _ = run_tests(kind, argv, env, dest, OUTFILE)
                again_after = ev_a2 is not None and rc_a2 == 0 and ev_a2["ran"] > 0
                reverted, _ = revert_patch(dest, code_patch, "code")
                again_before = None
                if reverted:
                    if built_with:
                        run(built_with, cwd=dest, timeout=BUILD_T, env=env)
                    rc_b2, ev_b2, _ = run_tests(kind, argv, env, dest, OUTFILE)
                    if ev_b2 is not None:
                        again_before = rc_b2 != 0 and ((ev_b2["failed"] > 0) == (ev_b["failed"] > 0))
                rec["flake_check"] = dict(after_repeats=again_after, before_repeats=again_before)
                if not again_after or again_before is False:
                    rec.update(outcome="FLAKY", detail="the result did not repeat on a second run")
                elif again_before is None:
                    rec["flake_check"]["note"] = "could not revert the code half to rerun the base"
        elif ev_a["failed"] > 0:
            rec.update(outcome="STILL_FAILS_AFTER_FIX", detail=tail_a)
        else:
            reason = ev_a.get("why") or ev_b.get("why") or tail_a[-500:]
            rec.update(outcome="RUNNER_ERROR",
                       detail="no test ran after the fix either: " + reason)
        return rec
    except Exception as exc:
        rec.update(outcome="ERROR", detail=f"{type(exc).__name__}: {exc}")
        return rec
    finally:
        rec["seconds"] = round(time.time() - t0, 1)
        shutil.rmtree(dest, ignore_errors=True)


def main() -> int:
    root, sample_path, workdir, out_path = sys.argv[1:5]
    sample = json.load(open(sample_path))
    os.makedirs(workdir, exist_ok=True)
    caches = {}
    for lang, sub in (("Go", "gomod"), ("Python", "uv"), ("TypeScript", "npm"),
                      ("JavaScript", "npm")):
        caches[lang] = os.path.join(workdir, "_cache", sub)
        os.makedirs(caches[lang], exist_ok=True)

    results = []
    for i, inst in enumerate(sample, 1):
        print(f"[{i}/{len(sample)}] {inst['lang']:<11} {inst['repo']}#{inst['number']}",
              flush=True)
        rec = one(inst, root, workdir, caches)
        print(f"      -> {rec['outcome']}  ({rec['seconds']}s)", flush=True)
        results.append(rec)
        json.dump(results, open(out_path, "w"), indent=1)
    print("\n=== outcomes")
    import collections
    for k, n in collections.Counter(r["outcome"] for r in results).most_common():
        print(f"  {n:>3}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
