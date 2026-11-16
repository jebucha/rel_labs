# Proposal

## Why

`build_inventory.yml` grew to 117 lines after `fix-build-inventory-race` added the two visibility waits. The waits are structurally identical blocks (~25 lines each, duplicated Jinja filter chains and identical block/rescue scaffolding), and the duplication is the main driver of the file's complexity: any future wait or any fix to the polling predicate has to be made in two places. This change extracts the wait into a single parameterized task file so the predicate, budget, and failure reporting exist exactly once. It is a pure, behavior-neutral refactor.

## What Changes

- New `tasks/wait_visible.yml`: one parameterized visibility wait — a `block` with a polling `set_fact` (`until` predicate re-evaluating the `ctrliq.ascender.controller_api` lookup, `retries: 30`, `delay: 2`) and a `rescue` that fails with a descriptive message — driven by include vars for the endpoint, object name, parent attribute, parent id, and the scope phrase used in the failure message.
- `build_inventory.yml`: the two inline wait blocks are replaced by two `include_tasks: tasks/wait_visible.yml` calls with vars; the id-resolution tasks and the create/update module tasks are unchanged.
- `tests/run-scenario.sh` is unchanged: the refactor keeps every rendered task name and the failure message byte-identical, so all seven existing scenario assertions remain valid without modification.
- No spec-level behavior changes: the change opts out of specs via `skip_specs: true` (`openspec/changes/extract-visibility-wait/.openspec.yaml`), so no delta spec exists and the base capability spec is untouched; the refactor's byte-identity contract is verified by base-spec scenario `T-ASCENDER-INVENTORY-BOOTSTRAP-005` (`tests/run-scenario.sh T-ASCENDER-INVENTORY-BOOTSTRAP-005`).

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
(none — the `ascender-inventory-bootstrap` capability's behavior is unchanged; this is a pure refactor, so `skip_specs: true` is set instead of inventing a requirement)

## Impact

- Code: `build_inventory.yml` (task-level refactor) and the new `tasks/wait_visible.yml` (a task file, parsed by `ansible-lint`; the master playbook's syntax check does not cover it because the include is dynamic).
- No changes to the `ctrliq.ascender` collection, the scenario harness, `tests/scenario_state.yml`, `tests/stub_ascender.py`, or any other playbook.
- Sequencing: this change depends on `fix-build-inventory-race` being archived first — its task 2.2 (live Ascender verification) is still open, and the live baseline should be established against the current file shape before it is refactored.
- Verification: `ansible-lint` on both task files, `ansible-playbook --syntax-check ascender_as_code.yml`, and scenario `T-ASCENDER-INVENTORY-BOOTSTRAP-005` (stub-backed; exercises both includes — the inventory wait succeeds against the stub, the source wait exhausts its budget), which requires no live Ascender.
