# Setup

This page gets CleanSweep running on your machine. The offline path (install, tests, the toy
cleanup) needs only Python 3.11 and git; Studio also needs Node 20 once, to build its page.
Docker and a Voyager key are needed only for the LLM features, the Docker tests and the
experiment runners.

The repository commands on this page (install, checks, offline runs, Studio, the hook) were run
on a fresh clone of `main` on macOS on Nov 13 and 14, with no key and Docker not running. The system
install commands (Homebrew, apt, WSL) and the Docker steps were not run for this page; if one
fails for you, file an issue with the error.

## What you need

| Tool | Version | Needed for |
|---|---|---|
| git | any recent | everything |
| Python | 3.11 (the runs used 3.11.16) | everything |
| Node.js | 20 or later | Studio, once, to build its web page |
| Docker Desktop (or Docker Engine on Linux) | any recent | the Docker tests, `clean --sandbox docker`, the experiment runners |
| A GitHub account with access to `ritwiz06/cleansweep` | | cloning; send Ritik your GitHub username |

Disk: the repository and its virtual environment take about 1 GB. The full experiment data and
Docker images take about 65 GB; you do not need them for your tasks unless your task says so.

### macOS

```bash
xcode-select --install          # git and the compilers, if you do not have them
brew install python@3.11 node@20
```

Install Docker Desktop from docker.com and turn on "Start Docker Desktop when you sign in".

### Windows (WSL2)

CleanSweep runs inside Linux on Windows. In PowerShell as administrator:

```powershell
wsl --install -d Ubuntu
```

Restart, open the Ubuntu app, and continue there:

```bash
sudo apt update
sudo apt install -y git software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa      # Ubuntu's own python3.11 may be missing
sudo apt install -y python3.11 python3.11-venv
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.bashrc && nvm install 20
```

- Clone the repository inside the Linux home folder (`~/cleansweep`), not under `/mnt/c/`.
  Files on the Windows drive are slow from Linux and confuse file permissions.
- Install Docker Desktop for Windows, then in its settings open Resources, WSL integration, and
  turn it on for Ubuntu. `docker info` inside Ubuntu should then answer.
- Studio runs inside Linux. Start it with `--no-browser` and open the address it prints in your
  Windows browser; WSL2 forwards `127.0.0.1`.

### Linux (Ubuntu or Debian)

```bash
sudo apt update
sudo apt install -y git python3.11 python3.11-venv    # add ppa:deadsnakes/ppa first if needed
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.bashrc && nvm install 20
```

For Docker, install Docker Engine from docs.docker.com and add yourself to the `docker` group
(`sudo usermod -aG docker $USER`, then log out and in).

## Get the code and install

```bash
git clone https://github.com/ritwiz06/cleansweep.git
cd cleansweep
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
cleansweep --help
```

The install took 33 seconds on the fresh clone. If it takes much longer, see
[the slow pip index](#pip-install-takes-20-minutes). Run `source .venv/bin/activate` again in
every new terminal; `cleansweep: command not found` means the environment is not active.

Set your git name and email once, if you have not:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"    # the email of your GitHub account
```

## Install the pre-push checks

```bash
bash scripts/tools/install_hooks.sh
```

This installs a git hook that runs the three checks CI runs (ruff, the offline tests and the
contract check) before every `git push`, and blocks the push if one fails. The offline tests
take 6 to 9 minutes. The hook lives in `.git/hooks`, so it is never committed. If you already
have a pre-push hook of your own, the script leaves it alone and says so.

## Check the install

```bash
ruff check .
pytest -q -m "not llm and not docker and not network and not slow"
python scripts/tools/check_contracts.py
```

On the fresh clone: ruff printed "All checks passed!", pytest "632 passed, 21 deselected" in
9 minutes, and the contract check printed OK for the stub and the real version of every
package. The deselected tests are the ones marked `llm` (need a key), `docker` (need Docker),
`network` and `slow`.

## Run it offline

None of these needs a key or Docker.

```bash
# the agent team on the toy repository, deciding by rules instead of the LLM
cleansweep clean tests/fixtures/toy_repo --no-llm --sandbox none --out ../toy-cleanup

# the Phase 1 pipeline: show the plan, then sweep and score with the hidden checks
python -m cleansweep plan --target tests/fixtures/toy_repo
python -m cleansweep sweep --target tests/fixtures/toy_repo --out results/raw/quickstart/report.json --hidden
python -m cleansweep show results/raw/quickstart/report.json

# rebuild the committed tables and figures; git should then show no change
bash scripts/reproduce_tables.sh
git status --short results/
```

- **`--sandbox none`** runs the toy repository's tests on your machine. Without it, `clean`
  picks Docker for any project in a git repository with no commit by your git email, which is
  every project in this repository for now. Without Docker running, the run then ends with
  "Result: stopped: Docker is not running; start it, or use --sandbox none for a project you
  trust, nothing applied". The toy repository is our own fixture, so running it on your
  machine is safe. Use the default (or `--untrusted`) for code you did not write.
- **`--out`** must be a new or empty folder outside the project. Pick a new name for each run.
  Without `--out`, the output goes next to the project, which for the toy repository is inside
  this repository.
- The offline toy cleanup took 15 seconds and ended "Result: everything runs. 9 edits applied;
  57 lines and 3 files removed; 8 suggestions."
- **The pipeline sweep prints `"behavior_changed": true`.** That is expected: without the LLM
  there is no judge and no probes, so the planted near-duplicate `_safe_round` (it passes every
  visible test) is applied. Catching it is the probes' job.

### Studio and Replay

```bash
cleansweep studio                     # opens http://127.0.0.1:8765
cleansweep studio --no-browser        # WSL2, or to open the address yourself
cleansweep studio --port 8800         # if 8765 is taken
```

The first start runs `npm ci` and builds the web page; on the fresh clone that took under a
minute. Without npm, build it by hand: `cd app/studio/frontend && npm ci && npm run build`.
Studio listens on your machine only. Replay plays the seven recordings in `demo/replay/` without
calling the LLM or running tests; every screen except Launch works offline. To see the demo, press
**Try the demo** on Home, or open **Runs** and pick `20261102_demo_feature_agentic`.

## Your Voyager key

Each of us uses our own ASU Voyager key. Create `.env` at the repository root:

```
VOYAGER_API_KEY=<your own key>
VOYAGER_BASE_URL=https://<the Voyager endpoint>/v1
VOYAGER_MODEL=qwen36-35b-a3b
VOYAGER_MODEL_ALT=glm-5-3
```

Ritik can tell you the endpoint address. Then check the connection:

```bash
python scripts/tools/voyager_ping.py
```

- `.env` is in `.gitignore`. Never commit it, never paste the key into an issue, a chat, a
  screenshot or a log, and never share your key with a teammate.
- With a key, `clean` runs the LLM steps (the Investigators, the LLM-guided Manager, the probes)
  and the pipeline runs its judge and probes. LLM replies are cached on disk, so a rerun asks
  nothing new.
- Your tasks do not need a key unless they say so. Every check in [tasks.md](tasks.md) runs
  offline.

## Docker

Docker runs the tests marked `docker`, `clean --sandbox docker`, and the experiment runners
(SWE-bench and AIDev projects run only in containers, with the network cut off before any of
their code runs). Start Docker Desktop, then:

```bash
docker info                                         # must answer
pytest -q -m docker tests/sandbox/test_container.py # pulls python:3.11 the first time
```

The SWE-bench Docker tests also need the downloaded data
([experiments.md](../experiments.md#getting-the-data)), which a fresh clone does not have.

## Troubleshooting

These are problems the project actually hit.

### pip install takes 20 minutes

On one of our laptops, the global pip settings listed an extra package index that did not
resolve, so pip retried it for every package and the install took 18 to 20 minutes. Check with
`pip config list`. If you see an `extra-index-url` you do not need, install without the
settings files:

```bash
PIP_CONFIG_FILE=/dev/null pip install -r requirements.txt
PIP_CONFIG_FILE=/dev/null pip install -e .
```

With that, the fresh-clone install took 33 seconds.

### Laptop sleep spoils long runs

A run's budget counts wall-clock minutes, so a run that overlaps a sleep loses time without
working, and an install that needs the network fails while asleep. Our rule: a run whose time
overlaps a sleep is rerun, and the spoiled run is never reported. For anything longer than a few
minutes:

- macOS: keep the laptop on power, lid open, and run the job under `caffeinate -dims` (for
  example `caffeinate -dims bash scripts/reproduce_tables.sh`). `caffeinate` stops idle sleep,
  not a lid-close sleep. Low Power Mode slows the CPU, so time-capped runs on battery were rerun
  on power.
- Linux: `systemd-inhibit --what=sleep <command>`.
- Windows: set "When plugged in, put my device to sleep" to Never while the job runs.

The offline checks and your tasks take minutes, so this matters only for experiment runs.

### Docker file sharing showed containers stale files

Docker Desktop shares host folders with containers through a file-sharing layer. Under load it
sometimes showed a container a deleted file, or the old content of a file that git or an atomic
write had just replaced (2 to 3 times in 60 to 100 such operations in our reproduction). Since
v2.1.1, the AIDev and `clean --sandbox docker` containers hold their own copy of the workspace,
synced and checked by hash before every command. If a check still finds a difference, the
command fails with "stale workspace" (exit 75) instead of passing. If you see it, run the job
again with less running at the same time.

Docker also stopped once with a laptop restart and did not come back by itself. Turn on "Start
Docker Desktop when you sign in", and check `docker info` before a Docker job.

### Other problems

| Problem | Fix |
|---|---|
| `python3.11: command not found` | install Python 3.11 (see your system above) |
| `cleansweep: command not found` | `source .venv/bin/activate` |
| `clean` ends "stopped: ..., nothing applied" | read the reason; for the toy repository add `--sandbox none`, or start Docker |
| `the output folder is not empty` | pass a new `--out` folder |
| Studio says npm is missing | install Node 20, or build by hand (see Studio above) |
| A push is blocked by the hook | run the three checks yourself, fix what fails, push again |
| The `docker` tests fail at once | Docker is not running: `docker info` |

More messages and what to do about them: [user guide](../user_guide.md#when-something-goes-wrong).
