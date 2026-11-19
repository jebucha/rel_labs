# AGENTS.md

Guidance for AI coding agents working in this repository.

## Test commands: control-plane playbooks (Molecule)

This section covers the root-level Ascender control-plane playbooks
(`ascender_as_code.yml`, `build_inventory.yml`) only; the other sections
in this file describe a different stack. The scenarios live under
`molecule/`; the two stub-backed ones run entirely locally in ~1 minute:

```sh
molecule test            # default scenario — happy path + idempotence re-run
molecule test -s exhaust # never-visible source — exact failure contract
```

Molecule is pinned at 26.11.0 and installed with
`uv tool install --python 3.13 "molecule==26.11.0" --with "ansible-core==2.19.11"`
(same ansible-core as the repo's `ansible-playbook`); setup details are
in `README.md` → Development.

`molecule test -s live` is **destructive**: it deletes and re-bootstraps
the 20031 objects on the lab Ascender. Only run it when intentionally
testing against the lab — its `prepare` fails early unless
`CONTROLLER_HOST` is in the allowlist in `molecule/live/prepare.yml` and
live credentials (`CONTROLLER_OAUTH_TOKEN` or
`CONTROLLER_USERNAME`/`CONTROLLER_PASSWORD`) are exported. The untracked
`.env` file holds those credentials — never commit it.

## Python environment: always use uv

This project's tooling was migrated to [uv](https://docs.astral.sh/uv/) (>= 0.13) and
`uv.lock` is the source of truth for the environment.

- **Run everything through `uv run`** — never activate `.venv` directly
  (no `source .venv/bin/activate`), never call the venv's binaries directly
  (`.venv/bin/python`, `.venv/bin/pytest`), and never use system `python`/`python3`,
  `pip`, or `venv`.
- Sync the environment with `uv sync` before running anything if the lockfile or
  `pyproject.toml` changed (or when in doubt).
- Add or pin dependencies with `uv add` — never edit `pyproject.toml` by hand and
  never `pip install` into the environment. Library pins must stay exact (see the
  runbook in `README.md` for the fetcher-update procedure).

Canonical commands (see `README.md` → Development):

```sh
uv sync                                                # create/sync the local environment
uv run python -m pytest tests/ -q --ignore=tests/e2e   # unit + API + logging tests
uv run python -m playwright install chromium           # one-time, for e2e
uv run python -m pytest tests/e2e/ -q                  # e2e UI tests (headless Chromium)
uv run python -m app.main                              # run locally, http://localhost:8000
```

Note: the project's declared test commands (e.g. in OpenSpec Test Requirement
blocks) are written as `python -m pytest …`; execute them through `uv run`
(i.e. `uv run python -m pytest …`) so they run in the locked uv environment.

## OpenSpec workflow

Feature work follows the OpenSpec change workflow (see `openspec/`):
`/opsx-propose` → `/opsx-apply` → `/opsx-validate` (fresh session, a model that
did not write the code) → `/opsx-archive`. Validation reports live under
`openspec/changes/<name>/validations/`.

Before archiving, bump the app's minor version for any change that ships
user-visible changes: run `uv version --bump minor` (never hand-edit
`pyproject.toml`). Under 0.x versioning, breaking changes also take a minor
bump.

## Conventions

- Vanilla JS UI with no build step, no framework, no CDN; all fetched content
  enters the DOM via `textContent` only (never `innerHTML`).
- No blocking I/O on the event loop — filesystem work goes through
  `asyncio.to_thread`.
- The single-flight semaphore governs only the YouTube fetch chain; read
  endpoints must not touch it.
