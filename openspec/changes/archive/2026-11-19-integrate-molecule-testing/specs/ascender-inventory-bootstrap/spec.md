# Spec Delta

## MODIFIED Requirements

### Requirement: Single-run convergence on a fresh Ascender
Running the playbook against an Ascender where the 20031 inventory does not yet exist SHALL, within a single run, create the inventory, create its SCM inventory source, trigger the initial inventory source update, and finish with every task succeeded.

#### Scenario: Fresh run creates the full chain
- **GIVEN** the inventory `"20031 Inventory"` does not exist in Ascender
- **WHEN** the playbook is run via the `ascender_as_code.yml` entry point
- **THEN** the run finishes with all tasks succeeded and the inventory, the `"20031-source"` inventory source, and an initial source update are present in Ascender (a job record for the `20031-source` update exists with a non-failed status)
- **ID**: T-ASCENDER-INVENTORY-BOOTSTRAP-001
- **File**: molecule/default/verify.yml::T-ASCENDER-INVENTORY-BOOTSTRAP-001
- **Command**: molecule test -s default
- **Pass**: Molecule exits 0 and the `default` scenario recap shows every action successful; the verify step asserts against the (stub) Ascender API that the inventory `"20031 Inventory"` and the `"20031-source"` source exist in organization 20031, and that a job record for the `20031-source` update exists with a non-failed status

#### Scenario: Partially bootstrapped state converges
- **GIVEN** the inventory exists but its source does not
- **WHEN** the playbook is run via the `ascender_as_code.yml` entry point
- **THEN** the run finishes with all tasks succeeded and the source created and its initial update triggered
- **ID**: T-ASCENDER-INVENTORY-BOOTSTRAP-002
- **File**: molecule/default/verify.yml::T-ASCENDER-INVENTORY-BOOTSTRAP-002
- **Command**: MOLECULE_STUB_SEED=inventory molecule test -s default
- **Pass**: Molecule exits 0 and the `default` scenario recap shows every action successful; the verify step asserts against the (stub) Ascender API that the source exists attached to the pre-seeded inventory and that a job record for the `20031-source` update exists with a non-failed status

### Requirement: Visibility wait before dependent operations
The playbook SHALL verify through the Ascender API that a newly created object is queryable before any task that references that object by name is executed, retrying with a delay until the object is visible or a bounded retry budget is exhausted.

#### Scenario: Inventory created but not yet visible
- **WHEN** the inventory task has created the inventory but the API does not yet return it
- **THEN** the playbook polls the API on a delay until the inventory is returned, and only then runs the inventory source task
- **ID**: T-ASCENDER-INVENTORY-BOOTSTRAP-003
- **File**: molecule/default/verify.yml::T-ASCENDER-INVENTORY-BOOTSTRAP-003
- **Command**: MOLECULE_STUB_INVENTORY_DELAY_SECONDS=3 molecule test -s default
- **Pass**: Molecule exits 0 even though the stub returns the created inventory only after a 3s delay — a run in which the inventory source task executed before the inventory became queryable would have failed its name lookup — and the verify step asserts the full chain is present in the API

#### Scenario: Source created but not yet visible
- **WHEN** the inventory source task has created the source but the API does not yet return it
- **THEN** the playbook polls the API on a delay until the source is returned, and only then runs the inventory source update task
- **ID**: T-ASCENDER-INVENTORY-BOOTSTRAP-004
- **File**: molecule/default/verify.yml::T-ASCENDER-INVENTORY-BOOTSTRAP-004
- **Command**: MOLECULE_STUB_SOURCE_DELAY_SECONDS=3 molecule test -s default
- **Pass**: Molecule exits 0 even though the stub returns the created source only after a 3s delay — a run in which the update task executed before the source became queryable would have failed its name lookup — and the verify step asserts the full chain is present in the API

#### Scenario: Retry budget exhausted
- **WHEN** an object created by the playbook is still not queryable after the retry budget is exhausted
- **THEN** the playbook fails the run with a visible error rather than skipping the dependent tasks
- **ID**: T-ASCENDER-INVENTORY-BOOTSTRAP-005
- **File**: molecule/exhaust/verify.yml::T-ASCENDER-INVENTORY-BOOTSTRAP-005
- **Command**: molecule test -s exhaust
- **Pass**: Molecule exits 0 (the expected converge failure is captured by the scenario, not propagated); the verify step asserts the captured failure contains `20031-source was not visible in inventory 20031 Inventory after 30 attempts` and the (stub) Ascender API shows no update job record for `20031-source`

### Requirement: Consistent source naming between create and update
The inventory source update task SHALL target the same inventory source name, within the same inventory, that the inventory source task creates.

#### Scenario: Update task finds the created source
- **WHEN** the inventory source task has created the source under its configured name
- **THEN** the inventory source update task resolves that exact name and does not fail with a not-found error
- **ID**: T-ASCENDER-INVENTORY-BOOTSTRAP-006
- **File**: molecule/default/verify.yml::T-ASCENDER-INVENTORY-BOOTSTRAP-006
- **Command**: molecule test -s default
- **Pass**: Molecule exits 0; the verify step asserts against the (stub) Ascender API that an update job record exists for the source named `20031-source` within inventory `20031 Inventory` with a non-failed status — an update task that resolved a different or missing source would have failed converge

### Requirement: Idempotent re-runs
Re-running the playbook against an Ascender where the inventory and source already exist and are queryable SHALL succeed with the create tasks reporting no change and the visibility waits passing on their first poll. The inventory source update task SHALL run only when the inventory source task reports changed, so a steady-state re-run re-triggers no update and reports zero changed tasks.

#### Scenario: Steady-state re-run
- **GIVEN** the inventory and the source exist and are queryable in Ascender
- **WHEN** the playbook is run again via the `ascender_as_code.yml` entry point
- **THEN** the visibility waits pass on the first poll, the create tasks report no change, the inventory source update task does not run, and the run finishes with all tasks succeeded
- **ID**: T-ASCENDER-INVENTORY-BOOTSTRAP-007
- **File**: molecule/default/molecule.yml::idempotence
- **Command**: molecule test -s default
- **Pass**: Molecule exits 0 and its built-in idempotence step re-runs converge against the still-running stub with zero tasks reporting changed, the `Update 20031 inventory` task skipped on the re-run, and no `FAILED - RETRYING` lines in the re-run output (the visibility waits pass on their first poll)

#### Scenario: Changed source attributes re-trigger the update
- **GIVEN** the inventory and the source exist and are queryable in Ascender, and the source's `source_path` differs from the playbook's configuration
- **WHEN** the playbook is run via the `ascender_as_code.yml` entry point
- **THEN** the inventory source task reports changed and the inventory source update task runs, triggering a new update
- **ID**: T-ASCENDER-INVENTORY-BOOTSTRAP-008
- **File**: molecule/default/verify.yml::T-ASCENDER-INVENTORY-BOOTSTRAP-008
- **Command**: MOLECULE_STUB_SEED=stale-source molecule test -s default
- **Pass**: Molecule exits 0 and the `default` scenario recap shows every action successful; the verify step asserts against the (stub) Ascender API that the source now carries the playbook's `source_path` and that a new update job record for `20031-source` exists with a non-failed status
