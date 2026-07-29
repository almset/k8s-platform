#!/usr/bin/env python3
"""
Custom Jinja2 filters for the platform engine.

topological_sort(resolved_components, direction)
    resolved_components: dict {name: {..., 'spec': {'dependencies': [...],
                                                      'optional_dependencies': [...]}}}
    direction: 'present' -> install order (dependencies before dependents)
               'absent'  -> cleanup order (dependents before their dependencies,
                                            i.e. reverse of install order)

Only edges to components that actually exist in resolved_components are
honoured: 'optional_dependencies' pointing at a component that isn't part of
this run are silently ignored (that's the whole point of "optional").
A hard 'dependencies' entry pointing at a component that doesn't exist in
resolved_components is a configuration error and raises AnsibleFilterError.
"""
from ansible.errors import AnsibleFilterError


def _build_graph(resolved_components):
    names = set(resolved_components.keys())
    graph = {name: set() for name in names}  # name -> set(names it depends on)

    for name, comp in resolved_components.items():
        spec = comp.get("spec", {}) or {}
        hard_deps = spec.get("dependencies", []) or []
        optional_deps = spec.get("optional_dependencies", []) or []

        for dep in hard_deps:
            if dep not in names:
                raise AnsibleFilterError(
                    "topological_sort: component '%s' declares hard dependency "
                    "on '%s', which is not present in platform_components / "
                    "catalog.yml for this run." % (name, dep)
                )
            graph[name].add(dep)

        for dep in optional_deps:
            if dep in names:
                graph[name].add(dep)
            # silently skip optional deps that are not part of this run

    return graph


def _kahn_sort(graph):
    """Return install order: dependencies first. Deterministic (sorted)
    tie-breaking so re-runs produce a stable, diffable order."""
    in_degree = {name: 0 for name in graph}
    # edge dep -> name  (name depends on dep, so dep must come first)
    dependents = {name: set() for name in graph}

    for name, deps in graph.items():
        for dep in deps:
            dependents[dep].add(name)
        in_degree[name] = len(deps)

    ready = sorted([n for n, deg in in_degree.items() if deg == 0])
    order = []

    while ready:
        node = ready.pop(0)
        order.append(node)
        for dependent in sorted(dependents[node]):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                ready.append(dependent)
        ready.sort()

    if len(order) != len(graph):
        remaining = sorted(set(graph.keys()) - set(order))
        raise AnsibleFilterError(
            "topological_sort: dependency cycle detected involving: %s"
            % ", ".join(remaining)
        )

    return order


def topological_sort(resolved_components, direction="present"):
    if not isinstance(resolved_components, dict):
        raise AnsibleFilterError(
            "topological_sort: expected a dict of components, got %s"
            % type(resolved_components)
        )
    if direction not in ("present", "absent"):
        raise AnsibleFilterError(
            "topological_sort: direction must be 'present' or 'absent', got '%s'"
            % direction
        )

    graph = _build_graph(resolved_components)
    install_order = _kahn_sort(graph)

    if direction == "present":
        return install_order
    return list(reversed(install_order))


def _kahn_levels(graph):
    """Group into dependency 'stages': all nodes with zero remaining
    in-degree at once, then remove them and repeat. Nodes within a stage
    have no dependency relationship between them (parallel-safe), and
    stage N+1 only ever depends on stages <= N. Deterministic ordering
    within a stage via sorted()."""
    in_degree = {name: 0 for name in graph}
    dependents = {name: set() for name in graph}

    for name, deps in graph.items():
        for dep in deps:
            dependents[dep].add(name)
        in_degree[name] = len(deps)

    remaining = set(graph.keys())
    levels = []

    while remaining:
        ready = sorted([n for n in remaining if in_degree[n] == 0])
        if not ready:
            raise AnsibleFilterError(
                "topological_levels: dependency cycle detected involving: %s"
                % ", ".join(sorted(remaining))
            )
        levels.append(ready)
        for node in ready:
            remaining.discard(node)
            for dependent in dependents[node]:
                in_degree[dependent] -= 1

    return levels


def topological_levels(resolved_components, direction="present"):
    """Same graph as topological_sort, but grouped into parallel-safe
    stages instead of a single flat order. Used for the execution plan
    display (render_plan.yml) — a 'Stage 1 / Stage 2 / ...' breakdown is
    far more legible than one long flattened list once you have more than
    a handful of components."""
    if not isinstance(resolved_components, dict):
        raise AnsibleFilterError(
            "topological_levels: expected a dict of components, got %s"
            % type(resolved_components)
        )
    if direction not in ("present", "absent"):
        raise AnsibleFilterError(
            "topological_levels: direction must be 'present' or 'absent', got '%s'"
            % direction
        )

    graph = _build_graph(resolved_components)
    install_levels = _kahn_levels(graph)

    if direction == "present":
        return install_levels
    # Reverse both the order of stages AND drop it back to a flat
    # per-node reverse would be wrong here — cleanup must undo the last
    # installed stage first, so we reverse the stage list itself, keeping
    # each stage's members (which have no ordering relationship anyway).
    return list(reversed(install_levels))


class FilterModule(object):
    def filters(self):
        return {
            "topological_sort": topological_sort,
            "topological_levels": topological_levels,
        }
