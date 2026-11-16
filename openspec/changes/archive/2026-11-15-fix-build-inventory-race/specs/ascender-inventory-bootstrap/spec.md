# Spec Delta

## Purpose

Defines the single-run, idempotent behavior of `build_inventory.yml` (run via the `ascender_as_code.yml` entry point) when bootstrapping the 20031 inventory, its SCM inventory source, and the initial inventory source update in Ascender.

## ADDED Requirements

### Requirement: Single-run convergence on a fresh Ascender
Running the playbook against an Ascender where the 20031 inventory does not yet exist SHALL, within a single run, create the inventory, create its SCM inventory source, trigger the initial inventory source update, and finish with every task succeeded.

#### Scenario: Fresh run creates the full chain
- **GIVEN** the inventory `"20031 Inventory"` does not exist in Ascender
- **WHEN** the playbook is run via the `ascender_as_code.yml` entry point
- **THEN** the run finishes with all tasks succeeded and the inventory, the `"20031-source"` inventory source, and an initial source update are present in Ascender (a job record for the `20031-source` update exists with a non-failed status)
- **ID**: T-ASCENDER-INVENTORY-BOOTSTRAP-001
- **File**: tests/run-scenario.sh::T-ASCENDER-INVENTORY-BOOTSTRAP-001
- **Command**: tests/run-scenario.sh T-ASCENDER-INVENTORY-BOOTSTRAP-001
- **Pass**: exit code 0, and the harness prints `PASS: T-ASCENDER-INVENTORY-BOOTSTRAP-001` after asserting the play recap shows `failed=0` and `skipped=0`, that the create, source and update tasks succeeded, and that each visibility wait ran before its dependent task

#### Scenario: Partially bootstrapped state converges
- **GIVEN** the inventory exists but its source does not
- **WHEN** the playbook is run via the `ascender_as_code.yml` entry point
- **THEN** the run finishes with all tasks succeeded and the source created and its initial update triggered
- **ID**: T-ASCENDER-INVENTORY-BOOTSTRAP-002
- **File**: tests/run-scenario.sh::T-ASCENDER-INVENTORY-BOOTSTRAP-002
- **Command**: tests/run-scenario.sh T-ASCENDER-INVENTORY-BOOTSTRAP-002
- **Pass**: exit code 0, and the harness prints `PASS: T-ASCENDER-INVENTORY-BOOTSTRAP-002` after asserting the play recap shows `failed=0` and `skipped=0`, that the source task and its visibility wait succeeded, and that the update task succeeded

### Requirement: Visibility wait before dependent operations
The playbook SHALL verify through the Ascender API that a newly created object is queryable before any task that references that object by name is executed, retrying with a delay until the object is visible or a bounded retry budget is exhausted.

#### Scenario: Inventory created but not yet visible
- **WHEN** the inventory task has created the inventory but the API does not yet return it
- **THEN** the playbook polls the API on a delay until the inventory is returned, and only then runs the inventory source task
- **ID**: T-ASCENDER-INVENTORY-BOOTSTRAP-003
- **File**: tests/run-scenario.sh::T-ASCENDER-INVENTORY-BOOTSTRAP-003
- **Command**: tests/run-scenario.sh T-ASCENDER-INVENTORY-BOOTSTRAP-003
- **Pass**: exit code 0, and the harness prints `PASS: T-ASCENDER-INVENTORY-BOOTSTRAP-003` after asserting the inventory visibility-wait task succeeded and ran before the `Add 20031 inventory source` task

#### Scenario: Source created but not yet visible
- **WHEN** the inventory source task has created the source but the API does not yet return it
- **THEN** the playbook polls the API on a delay until the source is returned, and only then runs the inventory source update task
- **ID**: T-ASCENDER-INVENTORY-BOOTSTRAP-004
- **File**: tests/run-scenario.sh::T-ASCENDER-INVENTORY-BOOTSTRAP-004
- **Command**: tests/run-scenario.sh T-ASCENDER-INVENTORY-BOOTSTRAP-004
- **Pass**: exit code 0, and the harness prints `PASS: T-ASCENDER-INVENTORY-BOOTSTRAP-004` after asserting the source visibility-wait task succeeded and ran before the `Update 2003 inventory` task

#### Scenario: Retry budget exhausted
- **WHEN** an object created by the playbook is still not queryable after the retry budget is exhausted
- **THEN** the playbook fails the run with a visible error rather than skipping the dependent tasks
- **ID**: T-ASCENDER-INVENTORY-BOOTSTRAP-005
- **File**: tests/run-scenario.sh::T-ASCENDER-INVENTORY-BOOTSTRAP-005
- **Command**: tests/run-scenario.sh T-ASCENDER-INVENTORY-BOOTSTRAP-005
- **Pass**: the run exits 2, the output contains `20031-source was not visible in inventory 20031 Inventory after 30 attempts`, and the `Update 2003 inventory` task did not run; the harness prints `PASS: T-ASCENDER-INVENTORY-BOOTSTRAP-005`

### Requirement: Consistent source naming between create and update
The inventory source update task SHALL target the same inventory source name, within the same inventory, that the inventory source task creates.

#### Scenario: Update task finds the created source
- **WHEN** the inventory source task has created the source under its configured name
- **THEN** the inventory source update task resolves that exact name and does not fail with a not-found error
- **ID**: T-ASCENDER-INVENTORY-BOOTSTRAP-006
- **File**: tests/run-scenario.sh::T-ASCENDER-INVENTORY-BOOTSTRAP-006
- **Command**: tests/run-scenario.sh T-ASCENDER-INVENTORY-BOOTSTRAP-006
- **Pass**: exit code 0, and the harness prints `PASS: T-ASCENDER-INVENTORY-BOOTSTRAP-006` after asserting the `Update 2003 inventory` task succeeded and the run log contains no not-found error

### Requirement: Idempotent re-runs
Re-running the playbook against an Ascender where the inventory and source already exist and are queryable SHALL succeed with the create tasks reporting no change and the visibility waits passing on their first poll.

#### Scenario: Steady-state re-run
- **GIVEN** the inventory and the source exist and are queryable in Ascender
- **WHEN** the playbook is run again via the `ascender_as_code.yml` entry point
- **THEN** the visibility waits pass on the first poll, the create tasks report no change, and the run finishes with all tasks succeeded
- **ID**: T-ASCENDER-INVENTORY-BOOTSTRAP-007
- **File**: tests/run-scenario.sh::T-ASCENDER-INVENTORY-BOOTSTRAP-007
- **Command**: tests/run-scenario.sh T-ASCENDER-INVENTORY-BOOTSTRAP-007
- **Pass**: exit code 0, and the harness prints `PASS: T-ASCENDER-INVENTORY-BOOTSTRAP-007` after asserting the create tasks report `ok` (not `changed`) and the run log contains no `FAILED - RETRYING` line
