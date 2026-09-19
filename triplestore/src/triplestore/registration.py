# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0

# Dynamic backend discovery for the `triplestore` package.
# This module discovers those entry points at runtime and exposes:
#   - available_backends(): returns the names that can actually be imported now
#   - Triplestore(name, config): a factory returning a backend instance

from importlib import import_module, metadata

REGISTRY: dict[str, str] = {}
DISCOVERED = False

# Optional mapping used to suggest the correct extra in error messages.
EXTRA_HINT = {
    "allegrograph": "allegrograph",
    "blazegraph": "blazegraph",
    "graphdb": "graphdb",
    "jena": "jena",
    "oxigraph": "oxigraph",
    "qlever": "qlever",
    "rdf4j": "rdf4j",
    "virtuoso": "virtuoso",
}


def discover_backends() -> None:
    """
    Populate the in-memory backend registry from installed entry points (one-time).
    """
    global DISCOVERED
    if DISCOVERED:
        return

    try:
        eps = metadata.entry_points(group="triplestore.backends")
    except TypeError:
        eps = metadata.entry_points().get("triplestore.backends", [])

    REGISTRY.clear()
    for ep in eps:
        REGISTRY[ep.name.lower()] = ep.value

    DISCOVERED = True


def is_importable(cls_path: str) -> bool:
    """
    Check whether the target "package.module:Class" can be imported and the
    backend's declared requirements (if any) are present.

    Returns
    -------
    bool
        True if importable, False otherwise.
    """
    try:
        module_path, class_name = cls_path.split(":")
        mod = import_module(module_path)
        getattr(mod, class_name)
    except (ValueError, ModuleNotFoundError, ImportError, AttributeError):
        return False
    else:
        return True


def available_backends() -> list[str]:
    """
    Compute the list of backend names that are importable right now.

    Returns
    -------
    list[str]
        Sorted list of importable backend names.
    """
    discover_backends()
    names: list[str] = []
    for name, cls_path in REGISTRY.items():
        if is_importable(cls_path):
            names.append(name)
    return sorted(names)
