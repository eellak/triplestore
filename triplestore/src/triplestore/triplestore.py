# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0

from importlib import import_module
from typing import Any

from triplestore.base import TriplestoreBackend
from triplestore.exceptions import BackendNotFoundError, BackendNotInstalledError
from triplestore.registration import EXTRA_HINT, REGISTRY, available_backends, discover_backends, is_importable


def Triplestore(backend: str, config: dict[str, Any]) -> TriplestoreBackend:
    """
    Factory that returns an instance of the requested triplestore backend.

    Parameters
    ----------
    backend : str
        The public backend name (e.g., "oxigraph").
    config : dict[str, Any]
        Backend-specific configuration.

    Returns
    -------
    TriplestoreBackend
        A concrete backend instance.

    Raises
    ------
    TypeError
        If `backend` is not a `str` or `config` is not a `dict`.
    ValueError
        If `backend` is an empty string (after stripping whitespace).
    BackendNotFoundError
        No entry point is registered under this name in the installed distribution.
    BackendNotInstalledError
        An entry point exists, but the backend is not importable (missing optional deps).
    TypeError
        The loaded class does not implement `TriplestoreBackend`.
    """
    if not isinstance(backend, str):
        msg = (
        f"Invalid type for parameter 'backend': {type(backend).__name__}.\n"
        f"Expected a string identifier (e.g., 'oxigraph', 'jena')."
    )
        raise TypeError(msg)
    if backend.strip() == "":
        msg = (
        "Invalid value for parameter 'backend': empty string.\n"
        "You must provide a non-empty backend name (e.g., 'oxigraph')."
    )
        raise ValueError(msg)
    if not isinstance(config, dict):
        msg = f"Invalid type for parameter 'config': {type(config).__name__}.\n"
        "Expected a dictionary of backend configuration parameters."
        raise TypeError(msg)

    discover_backends()
    name = backend.lower()
    cls_path = REGISTRY.get(name)

    supported = ", ".join(sorted(REGISTRY.keys())) or "none"
    available = ", ".join(available_backends()) or "none"

    # Unsupported in the installed distribution
    if not cls_path:
        msg = (
            f"Backend '{name}' is not recognized by this installation of 'triplestore'.\n\n"
            f"Supported backends in this package: {supported}.\n"
            f"Currently available backends: {available}.\n"
        )
        raise BackendNotFoundError(msg)

    # Supported but not importable
    if not is_importable(cls_path):
        extra = EXTRA_HINT.get(name, name)
        msg = (
            f"Backend '{name}' is not installed.\n"
            f"To install it, run: pip install triplestore[{extra}].\n\n"
            f"Supported backends: {supported}.\n"
            f"Currently available backends: {available}\n"
        )
        raise BackendNotInstalledError(msg)

    module_path, class_name = cls_path.split(":")
    cls = getattr(import_module(module_path), class_name)
    obj = cls(config)

    if not isinstance(obj, TriplestoreBackend):
        msg = f"{cls_path} does not implement TriplestoreBackend"
        raise TypeError(msg)

    return obj
