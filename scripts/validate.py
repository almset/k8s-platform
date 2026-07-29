#!/usr/bin/env python3
"""
make validate  →  python3 scripts/validate.py

Validates:
  1. catalog.yml                                against schemas/catalog.schema.json
  2. every roles/platform/<name>/component.yml's 'contract' key against schemas/contract.schema.json
  3. every driver referenced by the catalog has a driver.yml declaring driver_capabilities
  4. cross-check: every dependency referenced in catalog.yml exists as a key
     in catalog.yml (independent of which components are actually enabled
     for a given environment — that's checked at runtime by Ansible instead,
     since it legitimately varies per inventory).
"""
import json
import sys
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_yaml(path: Path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_against_schema(data, schema, label: str) -> bool:
    try:
        jsonschema.validate(data, schema)
        print(f"OK   {label}")
        return True
    except jsonschema.exceptions.ValidationError as e:
        path = " -> ".join(str(p) for p in e.absolute_path) or "(root)"
        print(f"FAIL {label}")
        print(f"     path:  {path}")
        print(f"     error: {e.message}")
        return False


def validate_catalog(schemas_dir: Path) -> tuple[bool, dict]:
    catalog_path = ROOT / "catalog.yml"
    if not catalog_path.exists():
        print(f"FAIL catalog.yml not found at {catalog_path}")
        return False, {}

    schema = load_json(schemas_dir / "catalog.schema.json")
    data = load_yaml(catalog_path)
    ok = validate_against_schema(data, schema, "catalog.yml")
    return ok, (data or {}).get("platform_catalog", {})


def validate_dependencies(catalog: dict) -> bool:
    ok = True
    names = set(catalog.keys())
    for name, entry in catalog.items():
        deps = (entry.get("spec", {}) or {}).get("dependencies", []) or []
        for dep in deps:
            if dep not in names:
                print(
                    f"FAIL catalog.yml: '{name}' depends on '{dep}', which "
                    f"has no entry in catalog.yml at all"
                )
                ok = False
    if ok:
        print("OK   catalog.yml dependency references")
    return ok


def validate_contracts(schemas_dir: Path, catalog: dict) -> bool:
    schema = load_json(schemas_dir / "contract.schema.json")
    ok = True

    for name in catalog:
        role_dir = ROOT / "roles" / "platform" / name
        component_path = role_dir / "component.yml"

        if not component_path.exists():
            print(f"FAIL {name}: missing roles/platform/{name}/component.yml")
            ok = False
            continue

        component_data = load_yaml(component_path) or {}

        if "contract" not in component_data:
            print(
                f"FAIL {name}: component.yml does not define a top-level "
                f"'contract:' key"
            )
            ok = False
            continue
        if "defaults" not in component_data:
            print(
                f"WARN {name}: component.yml has no top-level 'defaults:' "
                f"key (fine if the component genuinely has no configurable "
                f"values, otherwise likely a mistake)"
            )

        contract = component_data["contract"]
        contract_ok = validate_against_schema(
            contract, schema, f"{name}: component.yml contract"
        )
        ok = ok and contract_ok

        if contract_ok:
            ok = ok and validate_declared_phase_files(name, role_dir, contract)

    return ok


def validate_declared_phase_files(name: str, role_dir: Path, contract: dict) -> bool:
    """Mirrors roles/library/tasks/validate_contract.yml at authoring time,
    so CI catches a missing *_pre.yml/*_post.yml before a real run does."""
    ok = True
    phases = contract.get("phases", {}) or {}
    for phase_name, flags in phases.items():
        for hook, suffix in (("pre_driver", "pre"), ("post_driver", "post")):
            if flags and flags.get(hook):
                task_file = role_dir / "tasks" / f"{phase_name}_{suffix}.yml"
                if not task_file.exists():
                    print(
                        f"FAIL {name}: contract declares phases.{phase_name}."
                        f"{hook}=true but tasks/{phase_name}_{suffix}.yml is missing"
                    )
                    ok = False
    if ok:
        print(f"OK   {name}: declared plugin task files present")
    return ok


def validate_drivers(catalog: dict) -> bool:
    ok = True
    seen_drivers = set()
    for name, entry in catalog.items():
        driver_name = (entry.get("spec", {}) or {}).get("driver")
        if not driver_name or driver_name in seen_drivers:
            continue
        seen_drivers.add(driver_name)

        driver_dir = ROOT / "roles" / "library" / "drivers" / driver_name
        driver_yaml = driver_dir / "driver.yml"
        if not driver_yaml.exists():
            print(f"FAIL driver '{driver_name}': missing {driver_yaml}")
            ok = False
            continue

        data = load_yaml(driver_yaml) or {}
        caps = data.get("driver_capabilities")
        if not isinstance(caps, dict) or "install" not in caps or "cleanup" not in caps:
            print(
                f"FAIL driver '{driver_name}': driver.yml must define "
                f"driver_capabilities with at least 'install' and 'cleanup' keys"
            )
            ok = False
            continue

        for phase, implemented in caps.items():
            if implemented and not (driver_dir / "tasks" / f"{phase}.yml").exists():
                print(
                    f"FAIL driver '{driver_name}': driver_capabilities.{phase} is "
                    f"true but tasks/{phase}.yml is missing"
                )
                ok = False

        if ok:
            print(f"OK   driver '{driver_name}': capabilities match shipped task files")
    return ok


def main() -> int:
    schemas_dir = ROOT / "schemas"
    catalog_ok, catalog = validate_catalog(schemas_dir)
    deps_ok = validate_dependencies(catalog) if catalog else False
    contracts_ok = validate_contracts(schemas_dir, catalog) if catalog else False
    drivers_ok = validate_drivers(catalog) if catalog else False

    all_ok = catalog_ok and deps_ok and contracts_ok and drivers_ok
    print()
    print("VALIDATION PASSED" if all_ok else "VALIDATION FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
