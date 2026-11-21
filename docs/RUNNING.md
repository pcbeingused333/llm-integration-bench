# Running the full pool

**Status: ready.** The environment check and a three-minute test (step 5) pass on WSL with the same
outcomes as the machine this was developed on. The headline yield figure will be taken from this
run, restricted to the 120 instances in `data/sample_120.json`, so nothing is run twice.

This is written for Ubuntu under WSL 2 on Windows, and works the same on Linux. Expect 8 to 14
hours with 4 to 5 workers, 60 GB of free disk and 8 GB of memory or more (5 workers suit 8 cores
and 16 GB; with fewer, use `--workers 3` or `4`). The run is resumable: if it
stops, run the same command again and it continues from the last finished instance.

Keep Windows from sleeping while it runs (Settings, System, Power, Screen and sleep: set both
"When plugged in, put my device to sleep after" to Never). Sleep suspends WSL.

Every command here is complete and can be pasted as it is. Nothing is a placeholder.

## 1. Packages

```sh
sudo apt update
sudo apt install -y git build-essential python3 python3-venv curl golang-go
```

`build-essential` provides `gcc`, which some Go dependencies need (cgo). `golang-go` on Ubuntu 24.04
is Go 1.22; repositories that need a newer Go download their own toolchain automatically.

## 2. uv

The commands below are for zsh. If your shell is bash, replace `~/.zshrc` with `~/.bashrc`. None of
the commands contain trailing `#` comments, because zsh passes those to the command as arguments.

```sh
python3 -m venv ~/.uvenv
~/.uvenv/bin/pip install uv
echo 'export PATH="$HOME/.uvenv/bin:$PATH"' >> ~/.zshrc
. ~/.zshrc
```

## 3. Node 22 and pnpm

Do not skip this step because `node --version` already works. Under WSL, `node`, `npm` and `pnpm`
are often the **Windows** programs, which WSL leaves on the PATH, and they fail on Linux files
with errors such as `EISDIR ... \\wsl.localhost\...`. `check_env.sh` reports them as `WINDOWS`.
After this step `which node pnpm` must print paths that start with `/usr/local/bin`.

Download from nodejs.org and check the published checksum before installing. The `sha256sum`
line must print `...tar.xz: OK`; if it does not, stop.

```sh
cd /tmp
curl -fsSLO https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt
f=$(grep -o 'node-v22[^ ]*-linux-x64.tar.xz' SHASUMS256.txt | head -1)
curl -fsSLO "https://nodejs.org/dist/latest-v22.x/$f"
grep " $f\$" SHASUMS256.txt | sha256sum -c -
sudo tar -xJf "$f" -C /usr/local --strip-components=1
sudo npm install -g pnpm
rehash
which node pnpm
```

## 4. Get the code and the corpus

```sh
mkdir -p ~/bench-run && cd ~/bench-run
git clone https://github.com/pcbeingused333/llm-integration-bench
git clone --depth 1 https://github.com/pcbeingused333/merge-log-data
git -C merge-log-data fetch --depth 1 origin 52780cead917ca3e965ddb45dc176db93c1f986c
git -C merge-log-data checkout -q FETCH_HEAD
cd llm-integration-bench
sh scripts/check_env.sh ~
```

`check_env.sh` must end with `All toolchains present.` The corpus commit is the one the frozen pool
was scored from (`data/CORPUS`).

## 5. A three-minute test first

```sh
python3 -I scripts/run_pool.py ../merge-log-data data/scored_snapshot_2026-11-20.json /tmp/work-smoke ../smoke.jsonl --per-lang 1 --workers 1
```

It runs one random instance per language. Each line ends with an outcome; `REPRODUCED`,
`RUNNER_ERROR`, `SETUP_FAIL` and the others are all fine here, the point is that nothing crashes
and that `../smoke.jsonl` has three lines.

## 6. The full run

Everything measured so far used Node 22. If your Node is another version, switch for this terminal
only, which does not change your default (the toolchain file records what was used either way):

```sh
nvm install 22
nvm use 22
node --version
```

`node --version` should print `v22.` followed by numbers. Use `/tmp/work` as the work directory,
so that no account name ends up in paths:

```sh
cd ~/bench-run/llm-integration-bench
nohup python3 -I scripts/run_pool.py ../merge-log-data data/scored_snapshot_2026-11-20.json /tmp/work ../pool.jsonl --workers 5 > ../pool.log 2>&1 &
tail -f ../pool.log
```

To see how it is going at any moment, in the same folder:

```sh
python3 -I scripts/progress.py ../pool.jsonl
```

Pressing Ctrl-C on `tail` leaves the run going. Each line shows an estimate of the hours left and the
free disk. If the run stops, repeat the same
command. When it ends, run a retry pass for the instances that failed on environment grounds:

```sh
nohup python3 -I scripts/run_pool.py ../merge-log-data data/scored_snapshot_2026-11-20.json /tmp/work ../pool_retry.jsonl --retry-from ../pool.jsonl --workers 5 > ../pool_retry.log 2>&1 &
```

## 7. Publish the results

Error messages contain paths, which include your account name, and this repository is public.
Clean the files first; the script refuses to write anything it cannot clean:

```sh
cd ~/bench-run/llm-integration-bench
mkdir -p results
python3 -I scripts/sanitize_results.py ../pool.jsonl        results/pool_2026-11-20.jsonl       --workdir /tmp/work
python3 -I scripts/sanitize_results.py ../pool_retry.jsonl  results/pool_retry_2026-11-20.jsonl --workdir /tmp/work
cp ../pool.jsonl.toolchain.json results/pool_toolchain_2026-11-20.json
git checkout -b results-pool-2026-11-20
git add results
git commit -m "Add the full-pool results for the 2026-11-20 corpus"
git push -u origin results-pool-2026-11-20
```

If the push asks for a login, run `gh auth login` first (install the GitHub CLI with
`sudo apt install -y gh` if needed). The `toolchain` file records the tool versions the run used. Outcomes depend on them, so it is
published with the results. Then tell Claude the branch name; the results are read from there.
