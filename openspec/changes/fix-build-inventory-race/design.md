# Design

## Context

See proposal.md for motivation. Constraints that shape the approach: `build_inventory.yml` is a task file included by `ascender_as_code.yml` via `ansible.builtin.include_tasks` (a dynamic include), so `ansible-playbook --syntax-check` cannot validate it directly — `ansible-lint build_inventory.yml` is the parse check that works on the task file. The `ctrliq.ascender` create modules return as soon as the API accepts the POST (201), before the object is queryable; that is the race this change closes.

The repo has no playbook-level test framework (molecule suites exist for roles only, and this change touches no roles). This change adds a small scenario harness, `tests/run-scenario.sh`, so each spec scenario is addressable and executable instead of being a prose instruction: the harness arranges the scenario's Ascender state (`tests/scenario_state.yml`), runs the playbook, and asserts the scenario's outcome from the run log. Six scenarios need a live Ascender; the retry-exhaustion scenario runs against `tests/stub_ascender.py`, an API double that accepts the creates but never returns the inventory source.

## Goals / Non-Goals

**Goals:**
- `build_inventory.yml` converges in a single run: each create task is followed by a visibility wait that polls the Ascender API until the created object is queryable, scoped to the same organization (and, for the source, the same inventory) rather than name alone.
- Keep the change at task level: a name fix plus two added visibility waits inside `build_inventory.yml`, and no collection, role, or other-playbook changes. The only additions outside the task file are the test harness and its state-arrangement playbook.
- Every spec scenario has an addressable, runnable test entry point.

**Non-Goals:**
- Not making `inventory_source_update` idempotent at the module level — it reports `changed: true` on every run; the spec scopes idempotency to the create tasks.
- No new roles, no credential management; live-verification prerequisites stay as documented, out-of-repo configuration (`controller_cli.cfg` / `CONTROLLER_*` env vars).
- The stub is not a model of Ascender: it exists only to make the retry-budget scenario reproducible, and it is not evidence that the happy path works against a real instance.

## Decisions

- **Wait mechanism: the poll predicate lives in `until`, re-evaluated on every attempt; `set_fact` + `register` give the task something to retry.** `until` is re-templated per attempt (verified against ansible-core 2.19 `executor/task_executor.py`: `post_validate` runs once before the attempt loop, `_resolve_conditional(self._task.until, ...)` runs per attempt), while task arguments are templated once — so a lookup in the task arguments is a first-poll snapshot, and `until: <registered fact> | length > 0` would compare that stale snapshot 30 times and never converge. The predicate is therefore a concrete lookup expression, and `__inventory_visible` / `__source_visible` are kept only as that diagnostic snapshot. Verified locally: a `pipe`-lookup poll retried and succeeded on attempt 4, with the stored fact still holding the first-poll value. Alternatives considered: `ansible.builtin.uri` polling (would duplicate the collection's auth handling) and a dedicated polling module (none exists in the collection).
- **Failure reporting: `block` + `rescue` + `ansible.builtin.fail: msg:`.** `fail_msg` is not an Ansible task keyword (it is an `assert` module option), so a descriptive message cannot be attached to the polling task itself; the rescue wrapper produces the visible message and aborts the play before the dependent task. Verified locally: exhaustion exits 2, prints the rescue message, and skips the following task.
- **Bounded retry budget: `retries: 30` + `delay: 2` (~60 s).** The spec requires the run to fail loudly when an object never becomes visible; 30 × 2 s covers typical list-view propagation while bounding worst-case latency to ~60 s. The rescue message interpolates the observed `attempts` count.
- **Wait queries scoped by parent from the returned payload, with string-normalized id comparison.** The organization id is resolved once from the name `20031` via an `organizations` lookup (with the name re-checked locally, so a server-side filter that silently no-ops cannot make `first` pick an arbitrary organization), and the inventory id once from `20031 Inventory` scoped to that organization via a server-side `name` + `organization` query, mirroring the collection's own `resolve_name_to_id` pattern (cf. `plugins/modules/inventory.py`), with the name re-checked locally. The poll then queries by name and asserts the name and parent (`organization`, and `inventory` for sources) against the returned objects. Asserting the parent from the payload rather than trusting the list view's `organization`/`inventory` query parameters removes the open question about whether this Ascender build honours those filters, and keeps a same-named object elsewhere from satisfying the wait.

  Live verification (2026-11-15) found the Ascender serializes ids inconsistently: the `organizations` list view returns string ids (`"2"`) while the `inventories` list view returns integer foreign keys (`2`), so a raw `selectattr('organization', 'equalto', '2')` never matches and the wait exhausts its retry budget even though the object is visible. The predicates therefore compare `map(attribute=<parent>) | map('string')` against `<resolved id> | string` (via `select('equalto', …)`), which is type-agnostic. Two further constraints shaped the implementation: Ansible's templar rejects list comprehensions in task expressions with a syntax error, so the predicates are filter chains; and `selectattr` cannot transform the item side of a comparison, so the stringification is done with `map` before a `select`. Resolving the ids in their own named tasks also makes a missing organization fail as "Resolve the 20031 organization id" instead of a misleading visibility timeout. `tests/diagnose_visibility.yml` dumps the raw list-view payloads for future ground truth.
- **Task-file verification via `ansible-lint build_inventory.yml`.** `ansible-playbook --syntax-check` fails on a task file, and the master playbook's syntax check does not cover the included file (the include is dynamic); `ansible-lint` parses task files and is already clean on the current file.
- **Scenario harness rather than a unit-test framework.** `tests/run-scenario.sh <scenario-id>` is a plain bash dispatcher (no new runtime dependency): one function per scenario id, assertions parsed from the playbook's own log (`task_result`, `assert_order`, `assert_recap_clean`). `tests/scenario_state.yml` creates/removes the inventory and source that each scenario's GIVEN clause assumes. The retry-exhaustion scenario uses `tests/stub_ascender.py` (stdlib only) because a real Ascender cannot be asked to keep an object invisible for 60 s.

## Risks / Trade-offs

- [Worst-case ~60 s polling latency before a failed run reports] → Acceptable: the budget is bounded, the rescue message is visible, and steady-state re-runs pass the first poll.
- [Live verification depends on Ascender credentials and org state not stored in the repo] → Documented as prerequisites in the Test Strategy; no credentials committed. Six of the seven scenarios exit 3 (`PREREQUISITE UNMET`) rather than passing when credentials are absent.
- [`inventory_source_update` still reports `changed: true` on re-runs] → Out of scope (module-level behavior); the spec scopes idempotency to the create tasks, and the steady-state scenario asserts `ok` on the create tasks only.
- [The stub could drift from the real API's shapes] → The stub covers only the retry-exhaustion path, its responses mirror the fields the collection reads, and the other six scenarios remain live-only.
- [A payload-level parent assertion assumes the list view returns `organization` / `inventory` ids] → Both are standard fields of the inventory and inventory-source serializers; if a build omitted them the wait fails loudly instead of silently matching the wrong object.

## Migration Plan

Playbook-only change plus tests: commit the updated `build_inventory.yml` and the new `tests/` directory; no data or API migration. Rollback: `git revert` of the change commit.

## Test Strategy

- **Runner:** `tests/run-scenario.sh <scenario-id>`, from the project root. The script runs `ansible-playbook ascender_as_code.yml` (the playbook is the test vehicle) and asserts the scenario's Pass criterion from the run log.
- **Full-suite command:** `tests/run-scenario.sh all` (runs the seven scenarios in spec order, arranging state between runs).
- **Typed prerequisites:**
  - `cmd: ansible-playbook --version`
  - `cmd: python3 --version`
  - `file: tests/run-scenario.sh`
  - `file: tests/scenario_state.yml`
- **Prose prerequisites (not machine-checkable):** scenarios -001 to -004, -006 and -007 need a live Ascender reachable from the project root, with organization `20031` and SCM project `rel_labs` present, authenticated via `controller_cli.cfg` in the project root or `CONTROLLER_*` environment variables. Scenario -005 needs no Ascender: it starts `tests/stub_ascender.py` and points the playbook at it.
- **Per-scenario state:** `tests/scenario_state.yml -e scenario=<id>` removes the inventory (-001), ensures the inventory without the source (-002), or ensures both (-003/-004/-006/-007); -005 needs none.
- **Timing:** -005 takes ~60–70 s (30 retries × 2 s) and runs under a 180 s harness timeout; the other scenarios complete well within the 120 s per-block timeout on the happy path.

## Open Questions

- ~~Does the `inventory_sources` list view in this Ascender build accept `inventory` and `organization` (id) query params?~~ Resolved: the waits no longer depend on those filters — they query by name and assert the parent from the returned payload.
