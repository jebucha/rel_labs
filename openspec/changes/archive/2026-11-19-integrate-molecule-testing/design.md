# Design

## Context

The code under test is a control-plane playbook chain (`ascender_as_code.yml` →
`build_inventory.yml`, plus the new job-template task) that runs on `localhost` and drives the
Ascender (AWX-style) REST API through the `ctrliq.ascender` collection. It does not manage remote
nodes. Today it is tested by `tests/run-scenario.sh`, which starts `tests/stub_ascender.py` (a
Python HTTP double of the API), runs `ansible-playbook`, and asserts by grepping/awk-ing the
playbook stdout. The seven spec scenarios (`ascender-inventory-bootstrap`) hang off that harness
via per-scenario File/Command/Pass hooks.

Constraints: Molecule is not installed; `ansible-playbook`, `python3`, `docker` and `podman` are
available. The `ctrliq.ascender` collection reads `CONTROLLER_HOST`/`CONTROLLER_USERNAME`/
`CONTROLLER_PASSWORD`/`CONTROLLER_VERIFY_SSL` from the environment (already proven — the current
harness scenario -005 works exactly this way). The repo has no CI configuration.

## Goals / Non-Goals

**Goals:**
- Standard Molecule lifecycle (`converge → idempotence → verify`, plus `prepare`/`cleanup`) for
  the root playbooks, replacing the custom harness entirely.
- State assertions made against the (stub or live) Ascender API instead of log scraping.
- The job-template task exercised by the stub scenarios (light existence assertion) even though
  its contract is not yet spec'd.
- Canonical test commands: `molecule test` (the `default` stub scenario), `molecule test -s
  exhaust`, and the gated `molecule test -s live`.

**Non-Goals:**
- Spec'ing the `deploy_prometheus_server` job-template contract (follow-up change).
- CI configuration (no `.github/` exists yet; the canonical command is defined, adoption later).
- Container-based testing of the data-plane roles (`roles/prometheus`, etc. — their upstream
  `molecule/` scaffolding stays untouched and is not part of this change).
- Rewriting the playbooks into roles.

## Decisions

### D1: Molecule "playbook project" mode — root `molecule/`, no role wrapper
Molecule's documented pattern for testing root playbooks: a `molecule/` directory at the project
root, one subdirectory per scenario, each scenario's `converge.yml` being
`import_playbook: ../../ascender_as_code.yml`. The real entry point is tested, unmodified in
structure.

*Alternatives:* wrapping the playbooks in a role (Molecule's role-centric default — rejected:
forces restructuring of early-stage code and duplicates the entry point); pointing Molecule at
`build_inventory.yml` only (rejected: the entry point, not the task file, is the deployable unit
and must stay the thing under test).

### D2: `driver: default`, `managed: false`, local connection — no containers
The playbook runs on localhost against an external API; there is no node to provision.
`driver: name: default` with `options: { managed: false, ansible_connection_options:
{ ansible_connection: local } }` makes Molecule's "node" the local machine. `test_sequence`
omits `create`/`destroy` (no driver-managed infrastructure).

*Alternative:* docker/podman driver (rejected: a container would run nothing but `ansible-playbook`
against a localhost API — pure overhead and port/daemon coupling).

### D3: Stub lifecycle in `prepare`/`cleanup`, fixed port, env via the `ansible: env:` key
`prepare.yml` first kills a stale stub from a previous run (only if the PID's cmdline identifies
it as `stub_ascender.py` — guarding against a recycled PID), then starts
`molecule/stub_ascender.py` as a detached background process (a `nohup … &` shell task, not an
`async: N` job, which its timeout would terminate mid-run), records the PID in a file under the
repo-local `.molecule/` state directory (task 4.1 adds it to `.gitignore`), and waits for the
port; `cleanup.yml` kills it (same cmdline guard). Both plays are shared by the two stub
scenarios — `molecule/prepare_stub.yml` and `molecule/cleanup_stub.yml`, wired through each
scenario's `ansible.playbooks.prepare`/`cleanup` keys — while `live` keeps its own
`prepare.yml`/`cleanup.yml` (design D8). The stub listens on a fixed port (uncommon,
e.g. 18071) and each scenario's `molecule.yml`
sets the `CONTROLLER_*` variables under the `ansible: env:` key (the provisioner-level `env:` key
is a removed Molecule key — left in place it would be rejected or silently ignored, leaking
`os.environ` into the stub scenarios), so converge/idempotence/verify all see them without any
port plumbing.

*Alternatives:* random port per run (rejected: the `ansible: env:` key is static YAML — a random port
would need file-based hand-off into Ansible vars, and the controller library's documented input
is the environment); running the stub in-process from verify (impossible: converge and verify are
separate `ansible-playbook` invocations, the process must outlive converge).

### D4: Stub extensions (all behind env knobs, off/empty by default)
- `POST/GET /api/v2/job_templates/` — create and list, so the new job-template task converges.
- `POST /api/v2/inventory_sources/<id>/update/` — returns HTTP 202 with a job record (`id`,
  `status` non-failed, `url`) and keeps it queryable via `GET /api/v2/jobs/` — the module fails
  on any non-202 status and reads those fields — so verify can assert the update job record the
  spec's THEN clauses already promise.
- `PATCH /api/v2/inventories/<id>/` and `PATCH /api/v2/inventory_sources/<id>/` — apply the sent
  fields to the existing record and return 200 with the updated record; the module's update path
  (`update_if_needed` → `patch_endpoint`) issues a PATCH whenever a managed field differs, which
  scenario -008 (`stale-source`) and any seeded-field mismatch require.
- `MOLECULE_STUB_SEED=inventory|stale-source` — pre-populates state before converge:
  `inventory` (source absent — scenario -002), `stale-source` (source exists with a different
  `source_path` — scenario -008); absent = the empty default.
- `MOLECULE_STUB_INVENTORY_DELAY_SECONDS` / `MOLECULE_STUB_SOURCE_DELAY_SECONDS` — created
  objects are stored at create time but withheld from the list view until the delay elapses, so
  the happy-path visibility waits genuinely poll (scenarios -003/-004) instead of trivially
  passing on the first attempt.
- Inventory-source records echo every field the module may manage (`description`, `source`,
  `source_path`, `source_project`, `overwrite`, `update_on_launch`, …) exactly as sent, and
  job-template records echo every field the task sends (`job_type`, `organization`, `project`,
  `allow_simultaneous`, `ask_credential_on_launch`); every list-view record also carries `type`
  and `url` — the module's update path reads `existing_item['type']`/`['url']` before comparing
  fields, and their absence fails the idempotence re-run. Together this makes the modules' field
  comparison report no change on a steady-state re-run — required for the idempotence step to
  pass.
- `MOLECULE_STUB_SOURCE_NEVER_VISIBLE=1` — the inventory source is never added to the list view
  (today's hardcoded behavior, made opt-in); set by the `exhaust` scenario's `molecule.yml`, off
  in every other scenario.

The stub stays a minimal double of the endpoints the playbook touches; it is explicitly not a
substitute for the live scenario.

### D5: `exhaust` scenario captures the expected failure with a block/rescue wrapper
Molecule has no "expected failure" flag, and `molecule test` must exit 0. The scenario's
`converge.yml` is therefore a play (`hosts: localhost`) that wraps
`import_tasks: ../../build_inventory.yml` in a `block`/`rescue`; the rescue records the failure
message into a state file under the repo-local `.molecule/` state directory (task 4.1 adds it to
`.gitignore`; Molecule's own ephemeral directory is a separate runtime cache outside the repo),
which persists across the scenario's steps so `verify.yml` can read it. `verify.yml`
asserts the recorded message
matches the spec's exact text and that the API shows no update job. The wrapper imports the task
file rather than the full entry point deliberately: in the real entry point the job-template task
follows the inventory chain and is unreachable once the chain fails, so the wrapper's narrower
scope matches the scenario's contract (scenario -005).

*Alternative:* run `molecule converge` raw in a script expecting non-zero (rejected: abandons the
standard `molecule test` entry point and moves assertions out of Molecule).

### D6: Ansible-native verify (`uri` + `assert` / `controller_api` lookup) — not pytest
`molecule/default/verify.yml` queries the stub over plain HTTP (`ansible.builtin.uri` — the stub
needs no auth) and asserts final state: inventory and source present with correct parentage,
update job record with non-failed status, job template `deploy_prometheus_server` present in the
organization (light check). `molecule/live/verify.yml` asserts the same states using the
`lookup('ctrliq.ascender.controller_api', ...)` pattern the playbooks themselves use (auth via
the same `CONTROLLER_*` env).

*Alternative:* the Molecule-default pytest/testinfra verifier (rejected: testinfra verifies node
state, not API state; plain pytest would add a Python test environment for assertions that read
more naturally in Ansible and need no new dependencies).

### D7: Playbook change — conditional source update
`build_inventory.yml` registers the result of the `Add 20031 inventory source` task as
`inv_source_result` and the `Update 20031 inventory` task gains
`when: inv_source_result is changed`. Fresh runs and attribute-changed runs trigger the update;
steady-state re-runs skip it and report zero changed tasks, so Molecule's built-in idempotence
step (which fails on *any* changed task) passes unmodified. The job-template task in
`ascender_as_code.yml` stays unconditional; its steady-state no-change behavior is not assumed —
the idempotence re-run (task 4.2) executes it, so a module that reports changed fails that task
and must be resolved before the scenario is green.

### D8: `live` scenario — gated, arranges fresh state, no destructive cleanup
`molecule/live/prepare.yml` ports the state-arrangement logic from `tests/scenario_state.yml`
(delete the existing inventory/source) and additionally deletes the `deploy_prometheus_server`
job template — a new destructive action the retired harness never performed — so converge
performs a fresh bootstrap (the live idempotence step then covers the steady-state re-run).
`prepare` fails immediately with an explanatory message if `CONTROLLER_HOST` is unset, or does
not match the scenario's small lab-host allowlist (a guard so a misconfigured variable cannot
point the deletions at an unintended instance); the scenario is simply not invoked in
unauthenticated environments. `cleanup` is a no-op: the live instance ends in the bootstrapped
steady state, which is the lab's desired end state.

### D9: Tooling
Molecule installed at a pinned version in a dev environment that invokes the same
`ansible-playbook` the repo already uses; `molecule test`, `molecule test -s exhaust`, and the
gated `molecule test -s live` documented in a new `README.md` development section and a new,
scoped `AGENTS.md` test-commands section (existing `AGENTS.md` content untouched; reconciling it
is a follow-up) as the canonical test commands. No `molecule/requirements.yml` needed — the stub
and scenario files themselves use `ansible.builtin` only — but every scenario (stub and live
alike) imports playbooks that use `ctrliq.ascender.*` modules, and Molecule generates its own
`ansible.cfg` in the ephemeral directory, bypassing the repo's `collections_path`, so each
scenario's `molecule.yml` sets `ansible.cfg.defaults.collections_path` (under the same `ansible:`
key as the `env:` settings) to the repo's `./collections` directory, or converge cannot resolve
the `ctrliq.ascender.*` modules.

## Risks / Trade-offs

- [Fixed stub port collides with a process on the dev machine] → uncommon port; `prepare` waits
  for readiness and fails with a clear message if the port is already held by a non-stub
  responder; `cleanup` (and a trap in `prepare`) kills stale stub PIDs, only after verifying the
  PID's cmdline is the stub.
- [Stub drifts from real Ascender API semantics] → stub models only the endpoints the playbook
  touches and is documented as a double; the `live` scenario remains the source of truth for API
  behavior.
- [Molecule version changes behavior (sequence handling, env plumbing)] → version pinned at
  implementation; the scenario files are small enough to adapt if a pinned upgrade is needed.
- [Timing flakiness: 3s visibility delay vs the 30×2s retry budget] → 20× margin; the delay is a
  stub knob, not a playbook knob, and only affects the stub scenarios.
- [`exhaust` wrapper diverges from the real entry point] → confined to the failure-mode scenario,
  where the post-chain task is unreachable by definition; happy-path scenarios run the real entry
  point via `import_playbook`.
- [`live` scenario mutates a real instance] → the inventory/source deletion matches the retired
  harness, but the job-template deletion is a new destructive action on the live instance; the
  deletions are gated by the scenario's lab-host allowlist and called out in the scenario's
  `molecule.yml` description and the migration plan.
- [Idempotence step's "any changed fails" is stricter than the old harness] → exactly the
  intended tightening; any future always-changed task will be caught, which is the point.

## Test Strategy

- Runner: Molecule (pinned, task 2.1) driving the repo's existing `ansible-playbook`;
  Ansible-native verify (D6), no pytest/testinfra, no containers (D2).
- Full stub suite (no credentials): `molecule test` (`default`), `molecule test -s exhaust`, and
  the four `default` env variants from task 4.3; together they cover all eight spec scenarios.
- Gated: `molecule test -s live` — real Ascender, only with `CONTROLLER_HOST`/credentials set
  (D8); excluded from the stub matrix.
- Prerequisites (typed and machine-checkable — the validation workflow evaluates them):
  - `cmd: command -v ansible-playbook`
  - `cmd: command -v python3`
  - `cmd: command -v molecule`
  - `file: collections/ansible_collections/ctrliq/ascender`
- The live scenario additionally needs live credentials and a reachable Ascender; it is gated and
  excluded from the stub matrix, so no `env:` prerequisite is declared — its `prepare` fails
  cleanly (with an explanatory message) when `CONTROLLER_HOST` is unset.
- Each spec scenario's Test Requirement block maps to exactly one scenario/step above (a
  `verify.yml` assertion, the built-in idempotence step, or the `exhaust` capture).

## Migration Plan

Self-contained repo change, ordered so the repo is green at each step:

1. Make the conditional-update playbook change (`build_inventory.yml`).
2. Add `molecule/` (stub move + extensions, `default`, `exhaust`, `live` scenarios) and install
   the pinned Molecule; get `molecule test` and `molecule test -s exhaust` (the two stub
   scenarios) green.
3. Delete `tests/` (`run-scenario.sh`, `stub_ascender.py`, `scenario_state.yml`,
   `diagnose_visibility.yml`) and add the Molecule test commands to `README.md` (a new file —
   none exists) and a new, scoped `AGENTS.md` section (existing content untouched).
4. Update the `ascender-inventory-bootstrap` spec's scenario hooks (this change's delta) and run
   `molecule test -s live` once against the real Ascender when live credentials are available
   (otherwise record it as pending, per task 4.5).

Rollback: revert the change's commits — the old harness and playbook behavior return intact.

## Open Questions

- Exact Molecule version to pin and the precise install mechanism (uv tool vs dedicated venv) —
  decided at implementation; no impact on specs, approach, or task shape. Note the repo has no
  Python manifest yet (no `pyproject.toml`, `uv.lock`, or `requirements*.txt`) despite the uv
  mandate in `AGENTS.md` — the mechanism must include creating a reproducible home for the pin,
  and task 2.1 records the exact pin.
- Exact stub port number — implementation detail of D3.
