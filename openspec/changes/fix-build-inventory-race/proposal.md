# Proposal

## Why

`build_inventory.yml` does not converge on a single run against a fresh Ascender. The `ctrliq.ascender` create modules return as soon as the API accepts the POST (201), before the new object is queryable, so the dependent tasks fail their live name lookups: on a first run, task 2 (`inventory_source`) and task 3 (`inventory_source_update`) fail because the inventory is not yet visible, and on a second run the source created by task 2 is not yet visible when task 3 looks it up. Additionally, task 3 references an inventory source name (`"20031 source"`) that does not match the source task 2 creates (`"20031-source"`), so task 3 fails on every run regardless of timing.

## What Changes

- Fix task 3's `name` in `build_inventory.yml` from `"20031 source"` to `"20031-source"` so `inventory_source_update` targets the source that task 2 actually creates.
- Add a visibility-wait task after task 1: poll (via the `ctrliq.ascender.controller_api` lookup with `until`/`retries`/`delay`) until the inventory `"20031 Inventory"` is queryable before task 2 runs.
- Add a visibility-wait task after task 2: poll until the inventory source `"20031-source"` is queryable before task 3 runs.
- Add a `tests/` scenario harness (`run-scenario.sh`, `scenario_state.yml`, and a stub API double for the retry-exhaustion case) so every spec scenario is an addressable, runnable test instead of a prose instruction.
- Result: one playbook run converges (create inventory → wait → create source → wait → trigger update), and re-runs stay idempotent (waits pass on the first poll, create tasks report no change).

## Capabilities

### New Capabilities
- `ascender-inventory-bootstrap`: single-run, idempotent bootstrap of the 20031 inventory, its SCM inventory source, and the initial source update in Ascender via `build_inventory.yml`.

### Modified Capabilities
(none — no existing specs)

## Impact

- Code: `build_inventory.yml` (task-level edits; included by `ascender_as_code.yml`) plus the new `tests/` scenario harness.
- No changes to the `ctrliq.ascender` collection, Ascender API, or other playbooks.
- Behavior: first run gains a few seconds of polling latency only when objects are actually being created; steady-state re-runs are unchanged. Worst case: if a created object never becomes queryable, the run fails after ~60 s of polling (30 retries × 2 s delay) with the visibility-wait task's visible error.
