# rel_labs

Ansible playbooks that bootstrap the lab's Ascender control plane: the
`20031` inventory, its `20031-source` inventory source (an SCM-backed sync
of this repo), and the `deploy_prometheus_server` job template.

- `ascender_as_code.yml` — the entry point (also the playbook the
  `rel_labs` project syncs for its job templates).
- `build_inventory.yml` — the inventory bootstrap it includes.
- `collections/` — the local `ctrliq.ascender` collection plus the
  required AWS collections; `ansible.cfg` points the playbooks at it.

## Development

### Environment

- `ansible-core` 2.19.x — the playbooks run through the system
  `ansible-playbook` (`/usr/bin/ansible-playbook`, core 2.19.11);
  `ansible.cfg` supplies the inventory and collection paths.
- Molecule 26.11.0 for the scenario tests. Pin it exactly and install it
  in a uv tool environment pinned to the same ansible-core, so the
  scenarios exercise the playbooks under the same engine:

  ```sh
  uv tool install --python 3.13 "molecule==26.11.0" --with "ansible-core==2.19.11"
  ```

  `molecule --version` should then print
  `molecule 26.11.0 using python 3.13` with `ansible: 2.19.11`.

### Tests (Molecule scenarios)

The scenarios live under `molecule/`. The two stub-backed ones run
entirely locally against `molecule/stub_ascender.py` (a small fake of the
Ascender API on port 18071 that the scenarios start and stop themselves)
and take roughly a minute each:

```sh
molecule test            # default scenario — happy path + idempotence re-run
molecule test -s exhaust # source never becomes visible — exact failure contract
```

(Plain `molecule test` runs only the `default` scenario — Molecule's
`--scenario-name` default; pass `--all` to run every scenario, which
includes the gated live one below.)

The stub's state knobs drive the additional matrix variants (seeded list
views, delayed visibility, never-visible source); see
`molecule/stub_ascender.py` for the `MOLECULE_STUB_*` environment
variables.

### The live scenario

`molecule test -s live` is the gated, destructive scenario: its `prepare`
deletes the bootstrapped objects (inventory, source, job template) on the
real lab Ascender, and `converge` re-bootstraps them from scratch.
`prepare` refuses to run unless `CONTROLLER_HOST` names one of the lab
hosts allowlisted in `molecule/live/prepare.yml` and live credentials are
exported:

```sh
export CONTROLLER_HOST="http://ascender.jebucha.com"
export CONTROLLER_OAUTH_TOKEN="..."   # or CONTROLLER_USERNAME / CONTROLLER_PASSWORD
molecule test -s live
```

The local `.env` file holds the live credentials; it is untracked — never
commit it.
