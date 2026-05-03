# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0

import sys

import pytest


def main() -> int:
    files = [
        "triplestore/tests_GeoSPARQL/test_allegrograph.py",
        "triplestore/tests_GeoSPARQL/test_graphdb.py",
        "triplestore/tests_GeoSPARQL/test_jena.py",
        "triplestore/tests_GeoSPARQL/test_qlever.py"
    ]

    # Allow passing through extra pytest args, e.g. -q or -k pattern
    extra_args = sys.argv[1:]
    return pytest.main(files + extra_args)


if __name__ == "__main__":
    raise SystemExit(main())
