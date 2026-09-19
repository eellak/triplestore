# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0


class TriplestoreError(Exception):
    """Base exception for the triplestore library."""


class BackendNotFoundError(TriplestoreError, ValueError):
    """Raised when a backend is not registered or supported."""


class BackendNotInstalledError(TriplestoreError, ValueError):
    """Raised when a backend is supported, but not installed"""


class TriplestoreMissingConfigValue(TriplestoreError, ValueError):
    """Raised when a backend configuration is missing required keys."""
