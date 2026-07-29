# Optional Driver Capabilities

Declare these in `driver.yml` (default to `false`/absent = not implemented)
and ship the matching `tasks/<name>.yml` file. `run_phase.yml` only ever
calls what `driver_capabilities` declares `true`.

## validate
- Validate component configuration before install
- Check prerequisites
- Fail fast with a clear message on misconfiguration

## diff
- Show what would change (dry-run)
- Compare current state vs desired state

## history
- List previous releases/versions
- Show rollback candidates

## repair
- Fix broken installations (e.g. stuck Helm release in `pending-install`)
- Clean up failed releases
