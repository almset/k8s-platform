# Required Driver Structure

Every driver under `roles/library/drivers/<name>/` is a real Ansible role:

```
roles/library/drivers/<name>/
├── driver.yml          # capability contract (see below) — REQUIRED
└── tasks/
    ├── install.yml      # REQUIRED
    ├── cleanup.yml       # REQUIRED
    └── rollback.yml      # REQUIRED (may be a no-op / debug-only task)
```

Being a real role means drivers can also ship their own `defaults/main.yml`,
`vars/main.yml`, `handlers/`, `meta/main.yml` (for role dependencies), or a
`molecule/` test suite if they ever need to — nothing about the engine
assumes otherwise.

## driver.yml — capability contract

```yaml
driver_capabilities:
  install: true
  cleanup: true
  rollback: true
```

`run_phase.yml` loads this file explicitly (`include_vars`, not `stat()`)
before deciding whether to invoke a phase. A phase not declared `true` here
is skipped even if `tasks/<phase>.yml` happens to exist — the contract is
the source of truth, not the filesystem.

## tasks/install.yml
- Install or upgrade the component
- Handle repository setup (if applicable)
- Apply values and values_files
- Respect `rollback.strategy` from the catalog entry

## tasks/cleanup.yml
- Completely remove the component
- Clean up namespaces (if created by the driver)
- Remove repositories (if created by the driver)

## tasks/rollback.yml
- Execute rollback based on `rollback.strategy` (atomic/manual/none)
- Handle partial failures
- Log rollback actions

Variables available to every driver task file (set by `run_phase.yml`):

| Variable          | Description                                      |
|-------------------|---------------------------------------------------|
| `component_name`  | catalog key, e.g. `metrics_server`                 |
| `component`       | fully resolved component dict (defaults+catalog+contract) |
| `phase`           | `install` \| `cleanup` \| `rollback`               |
