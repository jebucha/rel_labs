# Design

## Context

See proposal.md for motivation. Constraints that shape the approach:

- `build_inventory.yml` is a task file included by `ascender_as_code.yml` via `ansible.builtin.include_tasks` (dynamic), so `ansible-playbook --syntax-check` cannot validate task files directly — `ansible-lint <task file>` is the parse check (same for the new `tasks/wait_visible.yml`).
- The polling predicate must live in `until`, not in task arguments: task arguments are templated once per task, while `until` is re-templated on every attempt (verified against ansible-core 2.19 in the `fix-build-inventory-race` design). The `ctrliq.ascender.controller_api` lookup has no caching, so each `until` evaluation issues a fresh API GET — the include vars referenced by the predicate are re-resolved on every poll for the same reason.
- The scenario harness (`tests/run-scenario.sh`) asserts on exact rendered strings from the run log: the task names `Poll for 20031 Inventory visibility` and `Poll for 20031-source visibility` (including inside `FAILED - RETRYING` lines), the rescue message `20031-source was not visible in inventory 20031 Inventory after 30 attempts`, the absence of `TASK [Update 2003 inventory]` on exhaustion, task ordering, and exit code 2. The harness is deliberately left untouched, so these strings are the **byte-identity contract** of this refactor.
- The in-flight change `fix-build-inventory-race` must be archived first: its task 2.2 (live Ascender verification) is still open, and the live baseline should be established against the current file shape before this refactor touches it.

## Goals / Non-Goals

**Goals:**
- Define the visibility wait (predicate, 30 × 2 s budget, rescue reporting) exactly once in `tasks/wait_visible.yml`; both call sites parameterize it via include vars.
- Behavior-neutral: rendered task names, failure message, retry budget, exit codes, and task order are all unchanged.
- Scenario `T-ASCENDER-INVENTORY-BOOTSTRAP-005` (stub-backed, no live Ascender) serves as the executable proof of behavior preservation.

**Non-Goals:**
- No changes to the id-resolution tasks, the create/update module tasks, the harness, `tests/scenario_state.yml`, or `tests/stub_ascender.py`.
- No generalization beyond the two existing call sites (no dynamic wait lists, no tags, no new waited objects).
- No spec delta (`skip_specs: true` — the capability's behavior is unchanged).

## Decisions

- **Mechanism: `include_tasks` + per-call-site `vars`.** A dynamic include evaluates its `vars` per call site, which is exactly the parameterization needed. Alternatives considered: `import_tasks` — rejected, imports are static expansions and cannot vary vars per call site; a role — rejected, two call sites inside one playbook is far below the reuse bar a role implies (directory structure, `defaults/vars` layers) for nothing.
- **Parameterization: five include vars.** `__wait_endpoint` (list-view endpoint), `__wait_name` (object name), `__wait_parent_attr` (`organization` or `inventory`), `__wait_parent_id` (the resolved parent id fact), `__wait_scope` (the message phrase: `organization 20031` / `inventory 20031 Inventory`). Task names and the failure message are fully templated, so `Poll for {{ __wait_name }} visibility` and `{{ __wait_name }} was not visible in {{ __wait_scope }} after {{ __wait_check.attempts | default(30) }} attempts` render byte-identically to the current names and message.
- **Predicate: unchanged semantics, vars interpolated, still in `until`.** The predicate keeps the exact semantics pinned by the race fix — query by name, assert name and parent from the returned payload, string-normalized id comparison, local name re-check — with the endpoint, name, parent attribute, and parent id coming from the include vars. The retry budget (`retries: 30`, `delay: 2`) stays hardcoded in the shared file: both call sites share it and scenario -005 asserts the `30 attempts` wording.
- **`map(attribute=<variable>)` for the parent attribute.** Jinja resolves the variable and passes its value as the attribute name; this is the only syntactic novelty introduced by the extraction. It is verified by `ansible-lint` plus scenario -005, which executes the attribute in both its values (the inventory wait uses `organization` and succeeds against the stub; the source wait uses `inventory` and exhausts).
- **One shared register name, `__wait_check`.** Both includes register into the parent scope under the same name; the second include overwrites the first. This is harmless and deliberate: each block's `rescue` reads `__wait_check.attempts` only at its own failure, by which point the most recent registration is its own. A comment in the shared file records the invariant so a later edit does not "fix" this into per-call-site names for no benefit.
- **Diagnostic snapshot kept inside the shared file.** The polling `set_fact` value remains the first-poll snapshot expression (`__wait_visible`), which the race fix kept for diagnostics; the extraction changes its cost from twice-payload to once-payload while preserving the value.
- **No version bump.** No user-visible behavior changes (rendered names and messages are identical), so the pre-archive minor-bump rule does not apply.

## Risks / Trade-offs

- [The two includes share a register name in parent scope; a future edit referencing `__wait_check` outside its block would read the wrong wait's result] → Invariant documented in a comment in the shared file; the rescue's self-containment is structural (the read happens inside its own block).
- [Templated task names move the concrete object names out of the main file into the include vars, reducing at-a-glance readability] → Each call site's `vars` block is the concrete declaration, and rendered log output is unchanged.
- [Include vars are templated at include time, so `__wait_parent_id` must be resolvable then] → Structural: each include sits after its id-resolution task, and a missing parent id still fails in that named resolution task (the named failure signal from the race fix is preserved).
- [The refactor overlaps the not-yet-archived `fix-build-inventory-race` on the same file] → Sequenced after that change archives; no code edits from this change until then.
- [Scenario -005 proves the parameterization (both a success and an exhaustion path) but not the live happy path] → The live scenarios -001/-003/-007 remain the live proof; optionally re-runnable against a live Ascender at apply time.

## Test Strategy

**Runner:** `ansible-lint` for task-file syntax checks; `ansible-playbook --syntax-check ascender_as_code.yml` for master playbook validation; `tests/run-scenario.sh <scenario-id>` for end-to-end behavior verification via a shell harness.

**Environment:** All stub-backed scenarios (specifically `-005`) run against `tests/stub_ascender.py` — no live Ascender required. Live scenarios (`-001`, `-003`, `-007`) require `controller_cli.cfg` in the project root or `CONTROLLER_*` environment variables pointing to a running Ascender instance; these are recorded as not applicable if unavailable.

**Prerequisites (machine-checkable):**
- `file: tests/run-scenario.sh`
- `file: tests/stub_ascender.py`
- `cmd: command -v ansible-playbook`
- `cmd: command -v python3`

**Steps:**
1. Lint the new shared task file: `ansible-lint tasks/wait_visible.yml` (expect exit 0).
2. Lint and syntax-check the refactored playbook: `ansible-lint build_inventory.yml && ansible-playbook --syntax-check ascender_as_code.yml` (both expect exit 0, verify exactly two `include_tasks: tasks/wait_visible.yml` occurrences remain).
3. Run stub-backed verification: `tests/run-scenario.sh T-ASCENDER-INVENTORY-BOOTSTRAP-005` — asserts byte-identity of rendered task names, failure message, and task ordering across both the success path (inventory wait) and exhaustion path (source wait).
4. *(Optional)* Run live scenarios against a running Ascender: `tests/run-scenario.sh T-ASCENDER-INVENTORY-BOOTSTRAP-001 -003 -007` to confirm happy-path, ordering, and steady-state behavior are preserved.

**Byte-identity contract:** The harness asserts exact strings from the run log (`Poll for 20031 Inventory visibility`, `Poll for 20031-source visibility`, `FAILED - RETRYING` lines, failure message text). Any divergence indicates a rendering regression and is treated as a test failure.

## Open Questions

(none — the byte-identity contract and the parameter set are fixed; the remaining syntactic risk, `map(attribute=<variable>)`, is resolved by scenario -005 during implementation.)
