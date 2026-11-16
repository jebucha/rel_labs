# Tasks

## 1. Prerequisite

- [x] 1.1 Confirm `fix-build-inventory-race` is archived before editing any code: its task 2.2 (live Ascender verification) must be complete and the change validated and archived, so the live baseline is established against the current file shape. Verify with `openspec list --json` that `fix-build-inventory-race` no longer appears in the active changes list and the spec now exists under `openspec/specs/ascender-inventory-bootstrap/`

## 2. Shared wait task file

- [x] 2.1 Create `tasks/wait_visible.yml` implementing the parameterized visibility wait per design.md: a `block` whose polling `set_fact` task is named `Poll for {{ __wait_name }} visibility`, keeps the diagnostic first-poll snapshot as `__wait_visible`, registers `__wait_check` (with a comment recording the shared-register invariant), and carries the predicate in `until` — `lookup('ctrliq.ascender.controller_api', __wait_endpoint, query_params={'name': __wait_name}, wantlist=True)` piped through `selectattr('name', 'equalto', __wait_name)`, `map(attribute=__wait_parent_attr) | map('string')`, `select('equalto', __wait_parent_id | string)`, `| list | length > 0` — with `retries: 30` and `delay: 2` hardcoded, plus a `rescue` task named `Report {{ __wait_name }} visibility failure` that runs `ansible.builtin.fail` with `msg: "{{ __wait_name }} was not visible in {{ __wait_scope }} after {{ __wait_check.attempts | default(30) }} attempts"`. Verify with `ansible-lint tasks/wait_visible.yml` exiting 0

## 3. Refactor build_inventory.yml

- [x] 3.1 Replace the two inline wait blocks with `include_tasks: tasks/wait_visible.yml` calls, each passing the five include vars — after the `inventory` task: `__wait_endpoint: inventories`, `__wait_name: "20031 Inventory"`, `__wait_parent_attr: organization`, `__wait_parent_id: "{{ __ascender_org_id }}"` (must be templated — a bare scalar passes through the templar as that literal string, so the predicate could never match the numeric id), `__wait_scope: "organization 20031"`; after the `inventory_source` task: `__wait_endpoint: inventory_sources`, `__wait_name: "20031-source"`, `__wait_parent_attr: inventory`, `__wait_parent_id: "{{ __ascender_inventory_id }}"` (templated for the same reason), `__wait_scope: "inventory 20031 Inventory"` — leaving the id-resolution tasks and the create/update module tasks unchanged, and updating the file's top comment block so it still accurately describes the predicate, the templating rationale, and the shared-wait location. Verify: `ansible-lint build_inventory.yml` and `ansible-playbook --syntax-check ascender_as_code.yml` both exit 0, and the file contains exactly two `include_tasks: tasks/wait_visible.yml` occurrences with no remaining inline polling predicate

## 4. Behavior verification

- [x] 4.1 Run `tests/run-scenario.sh T-ASCENDER-INVENTORY-BOOTSTRAP-005` (stub-backed, ~60–70 s, no live Ascender required) and verify the harness prints `PASS: T-ASCENDER-INVENTORY-BOOTSTRAP-005`, asserting the run exits 2, the `FAILED - RETRYING` line carries the rendered name `Poll for 20031-source visibility`, the exact message `20031-source was not visible in inventory 20031 Inventory after 30 attempts` appears, `Update 2003 inventory` did not run, and the inventory wait (`Poll for 20031 Inventory visibility`) succeeded against the stub — proving both the success and exhaustion paths of the parameterized wait, including `map(attribute=<variable>)` with both attribute values
- [x] 4.2 Against a live Ascender (prerequisite: `controller_cli.cfg` in the project root or `CONTROLLER_*` environment variables; record as not applicable if unavailable), run `tests/run-scenario.sh T-ASCENDER-INVENTORY-BOOTSTRAP-001`, `-003` and `-007` and verify each prints `PASS:`, confirming the live happy path, wait ordering, and steady-state first-poll passes with no `FAILED - RETRYING` lines — **not applicable**: no `controller_cli.cfg` in the project root and no `CONTROLLER_*` environment variables were available at apply time (verified; the harness would exit 3 at its prerequisite check)

## Workflow follow-up

- Validate the change with `openspec-validate-change` in a fresh session (a model that did not write the code).
- Archive the change with `openspec-archive-change` once validation passes. No version bump: the refactor is behavior-neutral (rendered task names and messages are byte-identical), so the pre-archive minor-bump rule does not apply.
