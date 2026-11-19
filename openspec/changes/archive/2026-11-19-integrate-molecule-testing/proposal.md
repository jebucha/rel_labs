# Proposal

## Why

The Ascender control-plane playbooks (`ascender_as_code.yml` → `build_inventory.yml`, plus the new
job-template task) are tested by a custom bash harness (`tests/run-scenario.sh` + a Python stub
API) that parses `ansible-playbook` stdout with `grep`/`awk`. As the playbooks grow (the
`deploy_prometheus_server` job-template task has no coverage at all), a standard, maintainable
workflow is needed: Molecule's converge → idempotence → verify lifecycle, with state assertions
made against the (stub) Ascender API instead of log scraping.

## What Changes

- Add Molecule as the test harness for the root playbooks (documented "test a playbook project"
  pattern: `molecule/` at the project root, no role wrapper, no container driver —
  `driver: default` with a local connection to localhost):
  - `molecule/default/` — stub Ascender scenario: converge (fresh bootstrap), idempotence
    (re-run must report zero changes), verify (assert API state), against a stub API process
    started in `prepare` and stopped in `cleanup`.
  - `molecule/exhaust/` — expected-failure scenario: the stub never makes the inventory source
    visible, converge is wrapped to capture the failure, verify asserts the exact retry-budget
    exhaustion message. Custom `test_sequence` (no idempotence).
  - `molecule/live/` — real Ascender scenario, gated on `CONTROLLER_HOST`/credentials being set;
    never run in unauthenticated environments.
- Extend the stub Ascender (`tests/stub_ascender.py` → `molecule/stub_ascender.py`): model
  `POST/GET /api/v2/job_templates/`, model the inventory-source `update/` call as a job record
  with a status, add a delayed-visibility mode (objects become queryable after a short delay) so
  the happy-path visibility waits actually poll, and listen on a fixed port whose
  `CONTROLLER_*` variables Molecule injects via the `ansible: env:` key.
- **BREAKING (playbook re-run behavior)**: the `Update 20031 inventory` task becomes conditional —
  it runs only when the inventory source task reports changed (fresh create or attribute change).
  Steady-state re-runs no longer re-trigger the SCM sync and report zero changes, which is what
  lets Molecule's standard idempotence step pass unmodified.
- Remove the existing harness: delete `tests/run-scenario.sh`, `tests/scenario_state.yml`
  (its per-scenario state arrangement moves into `molecule/live/prepare.yml`), and
  `tests/diagnose_visibility.yml` (an ad-hoc live diagnostic superseded by the `live` scenario),
  and the `tests/` directory with them.
- Install and pin Molecule as a development tool; the canonical test commands become
  `molecule test` and `molecule test -s exhaust` (the two stub scenarios — a bare `molecule test`
  runs only the `default` scenario) with `molecule test -s live` run only when live credentials
  exist. Document in a new `README.md` development section and a new, clearly scoped `AGENTS.md`
  test-commands section (the existing `AGENTS.md` content describes a different stack and is left
  untouched — reconciling it is a follow-up).
- Rewrite the executable test hooks (ID/File/Command/Pass blocks) of the
  `ascender-inventory-bootstrap` scenarios from `tests/run-scenario.sh` invocations to the
  corresponding Molecule scenario/step commands.
- Add the `deploy_prometheus_server` job-template task to `ascender_as_code.yml` (unconditional,
  so the stub scenarios exercise it and the idempotence re-run proves it reports no change on a
  steady-state run; its contract is intentionally not spec'd yet). Its `playbook` is a deliberate
  placeholder — `ascender_as_code.yml`, the only value the lab project's incomplete list view
  currently accepts — so the template's real target (`deploy_prometheus.yml`) and the task's full
  contract land in the follow-up change.

## Capabilities

### New Capabilities

(none — the job-template task is exercised by the stub scenarios and given a light verify
existence check, but its contract is intentionally not spec'd yet; that is a follow-up change)

### Modified Capabilities

- `ascender-inventory-bootstrap`: the inventory-source update task no longer runs unconditionally
  on every run — it is conditional on the source task reporting changed, so steady-state re-runs
  are true no-ops (the "Idempotent re-runs" requirement changes). Additionally, each scenario's
  executable test hook now runs via Molecule: the seven existing hooks collapse onto the
  `default` and `exhaust` stub scenarios, and the new `-008` scenario (which the retired harness
  never ran) is added with its hook on the `default` matrix; `live` is a manual,
  credential-gated check, not a test hook for any scenario.

## Impact

- Code: `molecule/` (new — scenarios, stub, `molecule.yml` per scenario), `tests/` (deleted),
  `build_inventory.yml` (register the source task result; make the update task conditional),
  `ascender_as_code.yml` (the new `deploy_prometheus_server` job-template task the stub scenarios
  exercise; placeholder `playbook` until the follow-up change specs its contract).
- Specs: delta on `ascender-inventory-bootstrap` (update-task semantics + test hooks).
- Tooling: Molecule added and pinned (runs against the existing Ansible installation; no new
  Python service dependencies — verify playbooks are Ansible-native, using `uri` + `assert`
  against the stub API).
- Docs: a new `README.md` development section and a new, scoped `AGENTS.md` test-commands
  section (existing content untouched) document the canonical Molecule test commands.
- No CI configuration exists in the repo yet; the canonical local command is defined by this
  change, CI adoption is out of scope.
