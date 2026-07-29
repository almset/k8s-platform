#!/usr/bin/env python3
"""
Scaffold a new roles/platform/<name> component.

    python3 scripts/generate_component.py my_component --driver helm
    python3 scripts/generate_component.py my_component --driver helm \
        --install-post --cleanup-post --install-pre

Guarantees, by construction, that this class of bug can't happen:
"component.yml declares phases.X.pre_driver/post_driver = true but the
matching tasks/X_pre.yml / X_post.yml file doesn't exist" — the script only
sets a flag to true if you pass the matching CLI flag, and creates the
task stub file for every flag it sets.

Produces a single roles/platform/<name>/component.yml (defaults + contract
together, explicit, no include_role side effects — see README) plus any
requested tasks/*.yml stubs. Does NOT add an entry to catalog.yml — that's
a WHAT decision (chart, repo, dependencies) the script can't guess; add it
by hand and run `make validate` afterwards.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

COMPONENT_TEMPLATE = """---
defaults:
  spec:
    values: {{}}

contract:
  apiVersion: platform.io/v1

  driver:
    enabled: true

  phases:
    install:
      pre_driver: {install_pre}
      post_driver: {install_post}
    cleanup:
      pre_driver: {cleanup_pre}
      post_driver: {cleanup_post}
    rollback:
      pre_driver: false
      post_driver: false

  events:
    install:
      pre: false
      post: false
    cleanup:
      pre: false
      post: false
"""

PLUGIN_TASK_STUB = """---
# {phase_label} — component_name / component available here.
- name: "{{{{ component_name }}}}: {phase_label} (TODO implement)"
  ansible.builtin.debug:
    msg: "{phase_label} stub for {{{{ component_name }}}} — nothing to do yet"
"""


def yaml_bool(value: bool) -> str:
    return "true" if value else "false"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="component name, e.g. cert_manager")
    parser.add_argument("--driver", default="helm", help="driver name (default: helm)")
    parser.add_argument("--install-pre", action="store_true")
    parser.add_argument("--install-post", action="store_true")
    parser.add_argument("--cleanup-pre", action="store_true")
    parser.add_argument("--cleanup-post", action="store_true")
    parser.add_argument("--force", action="store_true", help="overwrite existing role")
    args = parser.parse_args()

    role_dir = ROOT / "roles" / "platform" / args.name
    if role_dir.exists() and not args.force:
        print(f"roles/platform/{args.name} already exists. Use --force to overwrite.")
        return 1

    (role_dir / "tasks").mkdir(parents=True, exist_ok=True)

    (role_dir / "component.yml").write_text(
        COMPONENT_TEMPLATE.format(
            install_pre=yaml_bool(args.install_pre),
            install_post=yaml_bool(args.install_post),
            cleanup_pre=yaml_bool(args.cleanup_pre),
            cleanup_post=yaml_bool(args.cleanup_post),
        ),
        encoding="utf-8",
    )

    for phase, flag in (
        ("install_pre", args.install_pre),
        ("install_post", args.install_post),
        ("cleanup_pre", args.cleanup_pre),
        ("cleanup_post", args.cleanup_post),
    ):
        if flag:
            (role_dir / "tasks" / f"{phase}.yml").write_text(
                PLUGIN_TASK_STUB.format(phase_label=phase.replace("_", " ")),
                encoding="utf-8",
            )

    print(f"Created roles/platform/{args.name}/")
    print("Next steps:")
    print(f"  1. Add a '{args.name}' entry to catalog.yml (driver: {args.driver}, "
          f"dependencies, chart/repository, checks, rollback.strategy)")
    print(f"  2. Fill in roles/platform/{args.name}/component.yml's 'defaults:' with real values")
    print(f"  3. Implement the TODO stubs under roles/platform/{args.name}/tasks/")
    print("  4. make validate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
